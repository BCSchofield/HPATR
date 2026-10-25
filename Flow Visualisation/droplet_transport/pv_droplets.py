"""Build a ParaView state (.pvsm) for one droplet run, and a picture of its last frame (Phase 3a).

Runs under ParaView's own Python, not the phantom env:
    pvbatch pv_droplets.py <config.json>
The config (written by cfd_runner) gives the case, the output paths, the chamber and the run's timing.

What the state shows (open it in ParaView: File -> Load State, then Play):
- the flow during the spray on a cut through the spray hole (greys: white still, dark fast; it is the frozen flow, so
  it stays shown after switch-off, when the real air is coming to rest);
- the walls' edges (chamber, atomiser body, nozzle block, arm, port);
- every droplet as a dot coloured by size (log scale), stuck ones where they landed;
- hidden, to switch on with the eye: only the 0-30 µm band (its own linear colours), and only those still airborne;
- also hidden: Ben's own CfdOF views (jet_refined_chamber_v1_view.pvsm): cuts through the hole and the port, and
  streamlines from the hole, into the port and through the whole chamber, coloured by the air's speed on his scale.
A second tab, "split", puts the droplets (left) beside the air in Ben's views (right), cameras linked, seen as in
his comparison view; a picture of it at switch-off is saved too.
Opacity 1 and depth peeling off throughout (the Mac's "textures" warnings).
"""
import json
import sys

from paraview.simple import (AddCameraLink, AnnotateTime, AssignViewToLayout, Calculator, ColorBy, CreateLayout,
                             CreateView, ExtractBlock, FeatureEdges, ForceTime, GetAnimationScene,
                             GetColorTransferFunction, GetScalarBar, GetTimeKeeper, OpenFOAMReader, Outline, Render,
                             SaveScreenshot, SaveState, Show, Slice, StreamTracer, Text, Threshold)

# Ben's colour scale for the air (his views: 0-5 m/s, "Blue Orange (divergent)"), as saved in them
BEN_U = [0.0, 0.0564, 0.0564, 0.47, 0.85796, 0.243, 0.46035, 0.81, 1.492455, 0.356814, 0.745025, 0.954368,
         2.160645, 0.6882, 0.93, 0.91791, 2.5, 0.899496, 0.944646, 0.768657, 2.94113, 0.957108, 0.833819, 0.508916,
         3.530705, 0.927521, 0.621439, 0.315357, 4.2382, 0.8, 0.352, 0.16, 5.0, 0.59, 0.0767, 0.119475]

cfg = json.load(open(sys.argv[1]))
case = cfg["case"]

# ---- the flow (time 0 of the case: the CfdOF flow the droplets move through) ----
flow = OpenFOAMReader(registrationName="flow", FileName=case + "/flow.foam")
flow.SkipZeroTime = 0
flow.InvokeCommand("Refresh")                          # rescan, so time 0 (and the flow fields in it) are listed
flow.UpdatePipelineInformation()
flow.MeshRegions = ["internalMesh"] + ["patch/" + w for w in cfg["wall_patches"]]
flow.CellArrays = ["U"]
flow.LagrangianArrays = []
flow0 = ForceTime(registrationName="flow during the spray", Input=flow)
flow0.ForcedTime = 0.0
flow0.IgnorePipelineTime = 1
mesh = ExtractBlock(registrationName="air", Input=flow0)
mesh.Selectors = ["/Root/internalMesh"]
walls = ExtractBlock(registrationName="walls", Input=flow0)
walls.Selectors = ["/Root/boundary/" + w for w in cfg["wall_patches"]]
edges = FeatureEdges(registrationName="wall edges", Input=walls)
edges.FeatureAngle = 30.0
box = Outline(registrationName="chamber outline", Input=mesh)
cut = Slice(registrationName="flow on the cut through the hole", Input=mesh)
cut.SliceType = "Plane"
cut.SliceType.Origin = cfg["hole"]
normal = [0.0, 0.0, 0.0]
normal[cfg["slice_normal"]] = 1.0
cut.SliceType.Normal = normal
speed = Calculator(registrationName="air speed on the cut", Input=cut)   # its own colour map, apart from Ben's U
speed.AttributeType = "Cell Data"
speed.ResultArrayName = "air_speed"
speed.Function = "mag(U)"

# ---- Ben's CfdOF views, built as in his jet_refined_chamber_v1_view.pvsm ----
lo = [b[0] for b in cfg["inside"]]
hi = [b[1] for b in cfg["inside"]]
c = [(a + b) / 2 for a, b in zip(lo, hi)]
n2 = [0.0, 0.0, 0.0]
n2[cfg["flow_slices_normal"]] = 1.0
ben = {}                                  # name -> source, in the order shown in the Pipeline Browser
cut_hole = Slice(registrationName="Slice Through Orifice", Input=mesh)
cut_hole.SliceType = "Plane"
cut_hole.SliceType.Origin = cfg["hole"]
cut_hole.SliceType.Normal = n2
ben["Slice Through Orifice"] = cut_hole
if cfg.get("port_seed"):
    cut_port = Slice(registrationName="Slice Through Outlet", Input=mesh)
    cut_port.SliceType = "Plane"
    cut_port.SliceType.Origin = cfg["port_seed"]
    cut_port.SliceType.Normal = n2
    ben["Slice Through Outlet"] = cut_port


def tracers(name, centre, radius, direction, length):
    t = StreamTracer(registrationName=name, Input=mesh, SeedType="Point Cloud")
    t.Vectors = ["POINTS", "U"]
    t.IntegrationDirection = direction
    t.MaximumStreamlineLength = length
    t.IntegratorType = "Runge-Kutta 4-5"
    t.MaximumSteps = 2000
    t.InitialStepLength = 0.2
    t.ComputeVorticity = 1
    t.SeedType.Center = centre
    t.SeedType.Radius = radius
    t.SeedType.NumberOfPoints = 200
    ben[name] = t


tracers("Tracers From Orifice", [h + 0.001 * d for h, d in zip(cfg["hole"], cfg["spray_direction"])], 0.003, "BOTH",
        5.0)
if cfg.get("port_seed"):
    tracers("Tracers Outlet", cfg["port_seed"], 0.02, "BACKWARD", hi[cfg["up"]] - lo[cfg["up"]])
tracers("Tracers Whole", c, 0.1, "BOTH", 1.0)

# ---- the droplets ----
cloud = OpenFOAMReader(registrationName="droplets (reader)", FileName=case + "/cloud.foam")
cloud.MeshRegions = ["lagrangian/kinematicCloud"]
cloud.CellArrays = []
cloud.LagrangianArrays = ["d", "active", "U"]
size = Calculator(registrationName="droplets", Input=cloud)
size.AttributeType = "Point Data"
size.ResultArrayName = "size_um"
size.Function = "d*1e6"
band = Threshold(registrationName="0-30 µm band only", Input=size)
band.Scalars = ["POINTS", "size_um"]
band.LowerThreshold = 0.0
band.UpperThreshold = 30.0
band_c = Calculator(registrationName="0-30 µm band (colours)", Input=band)
band_c.AttributeType = "Point Data"
band_c.ResultArrayName = "band_size_um"
band_c.Function = "size_um"
air = Threshold(registrationName="still airborne only", Input=size)
air.Scalars = ["POINTS", "active"]
air.LowerThreshold = 0.5
air.UpperThreshold = 1.5

# ---- the views ----
def new_view(size):
    w = CreateView("RenderView")
    w.ViewSize = size
    try:
        w.UseColorPaletteForBackground = 0
    except AttributeError:
        pass
    w.Background = [1.0, 1.0, 1.0]
    w.OrientationAxesVisibility = 1
    w.DepthPeeling = 0
    try:
        w.DepthPeelingForVolumes = 0
    except AttributeError:
        pass
    return w


v = new_view([1400, 1000])
layout = CreateLayout(name="droplets")
AssignViewToLayout(view=v, layout=layout, hint=0)


def show(src, color=None, rep="Surface", view=None):
    d = Show(src, view or v)
    d.SetRepresentationType(rep)
    d.Opacity = 1.0
    try:
        d.InterpolateScalarsBeforeMapping = 0
    except AttributeError:
        pass
    if color is not None:
        d.ColorArrayName = ["POINTS", ""]
        d.AmbientColor = d.DiffuseColor = color
    return d


show(box, [0.35, 0.35, 0.35])
de = show(edges, [0.25, 0.25, 0.25])
de.LineWidth = 1.5
dc = show(speed)
ColorBy(dc, ("CELLS", "air_speed"))
ulut = GetColorTransferFunction("air_speed")
ulut.ApplyPreset("Grayscale", True)
ulut.InvertTransferFunction()
ulut.RescaleTransferFunction(0.0, cfg["flow_colour_max_m_s"])
ulut.AutomaticRescaleRangeMode = "Never"
dc.SetScalarBarVisibility(v, True)


def bar(lut, title, view=None):
    b = GetScalarBar(lut, view or v)
    b.Title = title
    b.ComponentTitle = ""
    b.TitleColor = b.LabelColor = [0.1, 0.1, 0.1]
    return b


bar(ulut, "air speed during the spray (m/s)")

dd = show(size, rep="Points")
dd.PointSize = 3.0
ColorBy(dd, ("POINTS", "size_um"))
slut = GetColorTransferFunction("size_um")
slut.ApplyPreset("Viridis", True)
slut.UseLogScale = 1
slut.RescaleTransferFunction(max(cfg["size_min_um"], 0.5), cfg["size_max_um"])
slut.AutomaticRescaleRangeMode = "Never"
dd.SetScalarBarVisibility(v, True)
bar(slut, "droplet size (µm)")

db = show(band_c, rep="Points")
db.PointSize = 4.0
ColorBy(db, ("POINTS", "band_size_um"))
blut = GetColorTransferFunction("band_size_um")
blut.ApplyPreset("Plasma", True)
blut.RescaleTransferFunction(0.0, 30.0)
blut.AutomaticRescaleRangeMode = "Never"
db.Visibility = 0
bar(blut, "0-30 µm band: size (µm)")
db.SetScalarBarVisibility(v, False)
da = show(air, rep="Points")
da.PointSize = 3.0
ColorBy(da, ("POINTS", "size_um"))
da.Visibility = 0
benlut = GetColorTransferFunction("U")
benlut.RGBPoints = BEN_U
benlut.ColorSpace = "Lab"
benlut.AutomaticRescaleRangeMode = "Never"


SPLIT_SHOWS = ("Slice Through Orifice", "Tracers Whole")   # Ben's layers shown in the split's right view


def show_ben(view, shown=()):
    for name, src in ben.items():
        d = show(src, view=view)
        ColorBy(d, ("POINTS", "U", "Magnitude"))
        d.Visibility = int(name in shown)


show_ben(v)                               # in the droplets tab: all there, all hidden
# pin the colour ranges last (showing a filtered copy rescales a shared colour map to its own data)
ulut.RescaleTransferFunction(0.0, cfg["flow_colour_max_m_s"])
slut.RescaleTransferFunction(max(cfg["size_min_um"], 0.5), cfg["size_max_um"])
blut.RescaleTransferFunction(0.0, 30.0)
benlut.RGBPoints = BEN_U
for b in (bar(ulut, "air speed during the spray (m/s)"), bar(slut, "droplet size (µm)"),
          bar(blut, "0-30 µm band: size (µm)")):
    b.RangeLabelFormat = "{:.3g}"

clock = AnnotateTime(registrationName="clock")
clock.Format = "t = {time:.1f} s"
dclock = Show(clock, v)
dclock.FontSize = 22
dclock.Color = [0.1, 0.1, 0.1]
dclock.WindowLocation = "Upper Left Corner"
note = Text(registrationName="what this run is")
note.Text = cfg["note"]
dnote = Show(note, v)
dnote.FontSize = 14
dnote.Color = [0.1, 0.1, 0.1]
dnote.WindowLocation = "Lower Left Corner"

# camera: a three-quarter view from the side the cut faces, a little above
span = max(b - a for a, b in zip(lo, hi))
offset = [0.0, 0.0, 0.0]
offset[cfg["slice_normal"]] = 1.6 * span
side = [a for a in range(3) if a not in (cfg["slice_normal"], cfg["up"])][0]
offset[side] = 0.9 * span
offset[cfg["up"]] = 0.25 * span * cfg["up_sign"]
v.CameraFocalPoint = c
v.CameraPosition = [a + b for a, b in zip(c, offset)]
up = [0.0, 0.0, 0.0]
up[cfg["up"]] = cfg["up_sign"]
v.CameraViewUp = up
v.ResetCamera(False)
v.CameraParallelProjection = 0

# ---- the split tab: the droplets (left) beside the air in Ben's views (right), cameras linked ----
left, right = new_view([1200, 1100]), new_view([1200, 1100])
split = CreateLayout(name="split: droplets | the air")
split.AssignView(0, left)
split.SplitHorizontal(0, 0.5)
split.AssignView(2, right)
for view in (left, right):
    show(box, [0.35, 0.35, 0.35], view=view)
    e = show(edges, [0.25, 0.25, 0.25], view=view)
    e.LineWidth = 1.5
    k = Show(clock, view)
    k.FontSize = 22
    k.Color = [0.1, 0.1, 0.1]
    k.WindowLocation = "Upper Left Corner"
dl = show(size, rep="Points", view=left)
dl.PointSize = 3.0
ColorBy(dl, ("POINTS", "size_um"))
dl.SetScalarBarVisibility(left, True)
bar(slut, "droplet size (µm)", left).RangeLabelFormat = "{:.3g}"
show_ben(right, SPLIT_SHOWS)
benlut.RescaleTransferFunction(0.0, cfg["flow_colour_max_m_s"])
benlut.RGBPoints = BEN_U
bar(benlut, "air speed during the spray (m/s)", right).RangeLabelFormat = "{:.3g}"
for view, title in ((left, "the droplets, coloured by size"), (right, "the air during the spray (Ben's views)")):
    t = Text(registrationName=title)
    t.Text = title
    dt = Show(t, view)
    dt.FontSize = 16
    dt.Color = [0.1, 0.1, 0.1]
    dt.WindowLocation = "Upper Center"
off2 = [0.0, 0.0, 0.0]
off2[cfg["flow_slices_normal"]] = 2.3 * span
for view in (left, right):
    view.CameraFocalPoint = c
    view.CameraPosition = [a + b for a, b in zip(c, off2)]
    view.CameraViewUp = up
    view.ResetCamera(False)
AddCameraLink(left, right, "split: the same camera")

scene = GetAnimationScene()
scene.UpdateAnimationUsingDataTimeSteps()
scene.PlayMode = "Snap To TimeSteps"
times = list(GetTimeKeeper().TimestepValues)
v.ViewTime = times[-1]
scene.AnimationTime = times[-1]
Render(v)
SaveScreenshot(cfg["png_end"], v, ImageResolution=[1400, 1000])
t_off = min(times, key=lambda t: abs(t - cfg["switch_off_s"]))
scene.AnimationTime = t_off
v.ViewTime = t_off
Render(v)
SaveScreenshot(cfg["png_switch_off"], v, ImageResolution=[1400, 1000])
left.ViewTime = right.ViewTime = t_off
SaveScreenshot(cfg["png_split"], split, ImageResolution=[2400, 1100])
SaveState(cfg["pvsm"])
print("saved", cfg["pvsm"])
