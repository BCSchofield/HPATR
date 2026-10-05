# Taguchi batch on the lab PC: run sheet and app guide

What this sheet does:

- **Parts A to E** get the lab PC ready, with commands you paste: open a window, pull the code,
  install what is missing, and run a self-test.
- **Part F** is a guide to the app, section by section. It tells you what goes where for tonight's
  27 runs (2026/10/05, 9 conditions x 3 repeats). **You set it up and press Run batch yourself.**
  No command in this sheet starts the batch. The same guide applies to any future campaign.
- **Parts G to I** cover watching the first run, leaving it overnight, and the morning.

**No Claude is needed on the PC.** Once you press Run batch, the batch runs by itself in the
background. Where something can go wrong, the sheet says what to do yourself. If you get stuck,
save the output (see *Saving output for later* at the end), don't leave the batch running, and
bring the output back to the Mac session.

**Timings:**
- About 45 minutes of your time, most of it watching run 1.
- The batch itself takes very roughly 8 to 10 hours on the RTX 4070 Ti SUPER. Start by about
  7 pm to have it finished in the morning.
- About 3 GB is written into each run folder. The .cine files are only read.

Every command is for **Command Prompt** (Start, type `cmd`, Enter): not the Anaconda Prompt, not
PowerShell. Paste each grey box as one line, and keep using the **same window**: the variables set in
A2 only exist in that window.

---

## 0. On the Mac, before you go

Put tonight's changes on GitHub so the PC can pull them:

```
cd /Users/benschofield/Documents/GitHub/HPATR && git add docs src/ai/Taguchi_Analysis_UI && git commit -m "Windows hardening for the overnight batch: no console windows, 64-bit ctypes, lock-safe file writes, --selftest, run sheet" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push
```

Plug the LaCie into the lab PC **directly** (not through a hub you might knock), and leave it
plugged in until the batch finishes. The job remembers each run by its full path, drive letter
included.

---

## A. Open the window (2 min)

**A1.** Open Command Prompt.

**A2.** Tell the window where Python and the code are:

```
set PY=C:\Users\55154111\AppData\Local\Programs\Python\Python311\python.exe
```
```
set HPATR=C:\Users\55154111\Documents\GitHub\HPATR
```

Check both. The first should print `Python 3.11.x`, and the second should find the file:

```
"%PY%" --version
```
```
dir "%HPATR%\src\ai\Taguchi_Analysis_UI\pipeline_spec.py"
```

If the second says *File Not Found*, find the repository:

```
where /r C:\Users\55154111 pipeline_spec.py
```

Then run `set HPATR=` followed by everything **before** `\src\ai\...` in the path it printed,
and repeat the check.

**A3.** Work from the repository folder:

```
cd /d "%HPATR%"
```

---

## B. Get tonight's code (2 min)

```
git -C "%HPATR%" checkout Testing
```
```
git -C "%HPATR%" pull
```
```
git -C "%HPATR%" log --oneline -1
```

The last line should be the "Windows hardening..." commit from step 0.

- If `git` is not recognised: in **GitHub Desktop**, choose the HPATR repo and the `Testing`
  branch, then click **Fetch origin** and **Pull**.
- If `pull` complains about local changes on the PC, put them aside safely (they're kept and
  can be brought back with `git -C "%HPATR%" stash pop`), then pull again:

```
git -C "%HPATR%" stash push -m "lab PC local changes"
```

---

## C. Install what is missing (5 min)

**C1.** Quick self-test. It only checks this PC and never touches a run:

```
"%PY%" -m src.ai.Taguchi_Analysis_UI --selftest --quick
```

If section **2. Packages** has any `FAIL`, it prints a line starting
`"C:\...\python.exe" -m pip install "numpy==..."`. **Copy that line exactly and run it**, then
repeat C1 until section 2 has no FAIL. numpy is pinned to the version already installed, so
nothing changes underneath torch, detectron2 or OpenCV.

| Needed by | Package (pip name) | Probably already on the PC? |
|---|---|---|
| the app window | `PySide6` | yes (the capture GUI uses it) |
| the workbook | `pandas`, `openpyxl` | yes (the capture GUI writes run_summary.xlsx) |
| figures | `matplotlib` | yes (the pipeline uses it) |
| p-values, confidence intervals | `scipy` | **maybe not: the likely one to install** |
| robust process checks | `psutil` | optional, worth installing |
| the pipeline | `opencv-python`, `cine-handler`, `pycocotools` | yes (the pipeline has run here) |
| inference | `torch` (CUDA build), `detectron2` 0.6 | yes. **Never** `pip install torch`: the plain wheel is CPU-only and would replace the CUDA one |
| tests (optional) | `pytest` | maybe |

If you'd rather install the usual set in one go, this is safe. numpy is pinned to the lab PC's
recorded 1.26.4, and packages already installed are left alone:

```
"%PY%" -m pip install "numpy==1.26.4" PySide6 pandas openpyxl matplotlib scipy psutil pytest
```

**C2.** Section **4** printed a line like `set LACIE=E:`. **Paste that line.** The checks
later in this sheet use it.

---

## D. Full self-test (2 min)

This test still never touches a real run. Its live part starts a background worker on **fake**
data in a temporary folder, kills it, resumes it, and deletes it all afterwards.

```
"%PY%" -m src.ai.Taguchi_Analysis_UI --selftest
```

It must end with **`READY for the batch`**. On the way, check:

- **3:** `CUDA works: NVIDIA GeForce RTX 4070 Ti SUPER ...`
- **4:** the LaCie letter, `model: ...\AI\Eden (... iteration 19000 ...)`, and `preflight passed`
- **5:** `27 runs, 27 with one .cine, 0 already measured, 27 to do`, and the design line
  `9 conditions x 3 replicates: replicates confirmed two independent ways`
- **6:** all PASS, with **no black console window flashing up**. If one does appear, it isn't
  harmful as long as nobody closes it, but note it for the Mac session.

If it says **NOT READY**: every FAIL line is followed by a `->` line saying what to do (install a
package, plug in the drive, and so on). Do that and run D again. If a FAIL has no fix you can apply,
**don't start the batch**: save the output (end of this sheet) and bring it to the Mac session.

*Optional, about 4 minutes:* the test suite. Some tests skip on Windows, and the real-data tests
skip because they look for the Mac's drive path. If the self-test said READY, a few FAILED tests here
don't stop you starting the batch. Save the output for the Mac session (end of this sheet).

```
"%PY%" -m pytest "%HPATR%\src\ai\Taguchi_Analysis_UI\tests" -q -p no:cacheprovider
```

---

## E. Make the PC safe to leave (3 min)

- **Windows Update:** Settings, then Windows Update, then **Pause updates** (1 week). If it says
  *Restart required*, restart **now**, then redo A in a new window. A forced update restart is the
  one thing the batch cannot block.
- **Power:** the batch keeps the PC awake by itself. For good measure, set Settings, System, Power,
  *When plugged in, put my device to sleep after* to **Never**.
- **Don't sign out or shut down.** Locking the screen (Win+L) is fine.
- **Close anything else using the GPU** (a training run, for example).

---

## F. The app, section by section: tonight's settings, and what each part is for

**F0. Open the app.** This only opens the window; nothing runs until you press **Run batch**.

```
"%PY%" -m src.ai.Taguchi_Analysis_UI
```

The window has three tabs at the top, **Batch**, **Taguchi** and **Settings**, and a
**CONSOLE** across the bottom of the Batch tab. After a few seconds the console prints the
pipeline check, ending in `PREFLIGHT PASSED`. If it says FAILED instead, **Run batch** stays
disabled and the console names what changed in the pipeline.

### F1. Settings tab (look here first)

Every field starts with the value the pipeline itself would choose, says where it came from, and
is marked **default**. A changed field says **edited**, and each has a **Reset**. Changes are
forgotten when the app closes, so every session starts from the defaults again.

| Field | What it is | Tonight | Change it when |
|---|---|---|---|
| Score threshold | AI confidence cut-off. Results go to `droplets_<thr>` | **0.3 (default)** | you're deliberately comparing thresholds. A different value gives a separate set of result folders |
| Frame stride | analyse every Nth frame of the cine | **10 (default)** | almost never. The note shows the frame spacing against the 20.5 ms decorrelation time and warns if frames would overlap |
| CI stride | spacing of the frames used for confidence intervals | **auto (default)**: 1 for these runs | never, normally. It is worked out per run from its frame rate |
| Inference device | where the AI runs | **auto → cuda.** There must be **no** orange CPU warning | only to force `cpu` for a test. `mps` is for Macs and experimental |
| Model folder | which trained model to use | **Eden, iteration 19000 (default)** | you've trained a new model and want to use it before it is promoted. Browse to its folder, and the row checks it has weights |
| Size-bin width / maximum | droplet-size bins for the analysis (Analyse only) | **25 / 200 µm (default)** | you want coarser or finer size-spread charts. It never affects the batch |

**Tonight: change nothing.** Just check the device row reads `auto → cuda` and the model is Eden.

### F2. Batch tab, left side: SELECTED RUNS

- **+** opens a folder picker. You can pick a **day** folder (every run inside is added), or
  several run or day folders at once (Ctrl-click). Dragging folders onto the list works too.
- Each run appears with a **tick box**. Ticked runs are in the batch. A run that can't be processed
  (no .cine, bad folder name) is greyed out and its tooltip says why. **Remove** and **Clear** edit
  the list.
- The line under the list summarises the selection, for example *27 runs, 9 conditions x 3*.
- **"N of the selected runs already have results. For those, Run batch will:"** appears only when
  some ticked runs were analysed before. The choice tells the batch what to do with them:
  - *Use their existing results (don't re-run them)*: the safe default. They are still included in
    the analysis.
  - *Re-measure only (keep frames + AI predictions)*: after a change to the measurement or classical
    code. Much faster.
  - *Redo everything, including the AI*: after changing the inference code itself. (A newer model is
    noticed automatically.)
- An orange warning appears if the ticked runs were measured with **different sizer versions**.
  They can't be analysed together until the older ones are re-measured.

**Tonight:** click **+**, go to the LaCie, then `Experiments\2026\10`, click the **`05`** folder
once, and press **Choose** (or **Open**). Expect **27 runs, all ticked**, and the summary line with
**9 conditions x 3**. The "already have results" choice won't appear, because none have results yet.

### F3. Batch tab, left side: OUTPUT FOLDER

Where the batch keeps its job files (`_job\`: progress, logs and timings), and where Analyse later
writes the report, workbook and figures. **Nothing for the runs themselves goes here**: their
frames and results always go inside each run folder. Use **one output folder per campaign**. If
you reopen the app and choose a folder that holds an unfinished batch, the app reattaches to it.

**Tonight:** click **Browse…**, go to the LaCie's `Experiments\Taguchi` folder, use the dialog's
**New folder** button to make **`Taguchi_ReRun_2026-10-05`**, select it, and confirm. The path
shows beside the button.

### F4. Batch tab, right side: OUTPUTS THAT WILL BE CREATED

This shows every file the batch will make, using **one example run**. The disk and time cost is
shown underneath.

- **Grey locked ticks** are always made: frames, `predictions.json`, `droplet_sizes.csv`,
  `summary.json`, the classical results, the histograms, and the **extreme-frame images** (a few
  PNGs per run showing the highest and lowest D32 and atomised fraction).
- **`EVERY frame`** (it appears twice, once for the AI measurement and once for the classical
  stage, but it is one choice): draws every frame as a PNG. That adds hours and about 4 GB per run.
  Tick it only when you need to look through every frame.
- **`csv/ flat CSVs + results JSON`** and **`odd/ odd-frame flags + images`**: extras that
  **Analyse** writes into the output folder. They don't affect the batch. Tick them before pressing
  Analyse if you want them.

**Tonight:** leave every tick as it is. **EVERY frame stays off.**

### F5. Run batch, and the buttons it turns into

**Run batch** is enabled once the pipeline check has passed, runs are ticked and an output folder is
chosen. If it is greyed out, hover over it to see why. Pressing it shows a **confirmation**: how many
runs will be processed, the image mode, the disk needed, and where the reports go. Read it, then
press **Yes**.

While a batch runs, the button turns into:
- **Stop after this run**: finish the current run, then stop. It can be resumed later.
- **Stop now** (red): interrupt immediately. The interrupted run is redone on resume.

Afterwards, it turns into:
- **Resume (k/N done)**: continue an interrupted batch. Finished runs are kept.
- **Retry failed (n)**: re-run only the runs that failed, reusing anything that completed.
- **New batch**: start afresh from the current selection. The old job is archived, not deleted.

**Tonight:** press **Run batch**. The confirmation should say *Run the analysis on 27 run(s)*,
*Images: extreme frames only*, and *Reports go to: ...\Taguchi_ReRun_2026-10-05*. Press **Yes**.

### F6. The CONSOLE

The console shows one line per event: `▶` for a run starting, the stage progress, `✔` for a run
done with its time, `⚠` for warnings and `✖` for failures. The **status line** on the right repeats
every few seconds with the run, the stage, frames done, and the ETA for this run and for the whole
batch. **If nothing changes for about 90 seconds**, it says the batch looks **stalled**.

The batch runs in a background process. **Closing the window does not stop it**, and reopening the
app and choosing the same output folder reattaches to it.

---

## G. Watch run 1 all the way through (about 20 min): the real test

Stages: **extract frames, background, inference, measurement, classical**. Check each of these:

- **No black console windows appear** at any stage.
- The console updates at least every few seconds, and the status line shows the stage, frames and
  ETA.
- Inference is on the GPU. Once inference has started, this should print `device: cuda`. It only
  reads the run's log:

```
findstr /i "device" "%LACIE%\Experiments\Taguchi\Taguchi_ReRun_2026-10-05\_job\logs\00_090432_3000sccm_300rpm_4000sps_or1.2_bh1.log"
```

- The console shows **`✔ 090432_... done in ...`**, roughly 15 to 20 minutes in. The batch ETA then
  settles at roughly **7 to 10 hours**.
- Run 1's folder has its results. Both of these should list a file (read only):

```
dir "%LACIE%\Experiments\2026\10\05\090432_3000sccm_300rpm_4000sps_or1.2_bh1\shadowgraph\analysis\droplets_0.30\summary.json"
```
```
dir "%LACIE%\Experiments\2026\10\05\090432_3000sccm_300rpm_4000sps_or1.2_bh1\shadowgraph\analysis\liquid_0.30\classical_summary.json"
```

**If run 1 fails** (a red ✖): the batch moves on to run 2 by itself. If run 2 fails the same way,
press **Stop now** and don't leave it overnight. The reason is in the ✖ line and at the end of the
run's log (`_job\logs\00_...log` in the output folder, open it in Notepad). Bring that folder's
`_job` to the Mac session on the LaCie. Nothing is harmed: anything half-written in a run folder is
redone next time.

---

## H. Check it survives you leaving (2 min)

1. **Close the app window** (the X). The batch keeps going.
2. Reopen it (the F0 command), and under OUTPUT FOLDER **Browse…** to the same
   `Taguchi_ReRun_2026-10-05`. The console prints **`found a batch ... re-attached`** and the progress
   carries on. Close it again.
3. *(Optional)* This only reads the job and starts nothing:

```
"%PY%" -m src.ai.Taguchi_Analysis_UI.jobctl status "%LACIE%\Experiments\Taguchi\Taguchi_ReRun_2026-10-05"
```

It should say `worker: running`, which run it is on, and an ETA.

You can close the Command Prompt too. **Leave the PC on and the LaCie plugged in.**

---

## I. In the morning

**I1. Did it finish?** Open the app (redo A2 and A3 first, since the variables are per window).
Under OUTPUT FOLDER, Browse… to `Taguchi_ReRun_2026-10-05`. The console replays what happened.
You're hoping for **27 done**.
- Some failed: press **Retry failed (n)**.
- It stopped part-way (the PC restarted, say): press **Resume (k/27 done)**. Finished runs are kept.

**I2. The analysis: the Taguchi tab.**
- The **banner** at the top says whether the design is what it should be. Expect *27 runs =
  9 conditions x 3 replicates: replicates confirmed two independent ways (Notes and factor levels)*.
- The **table** has one row per run: a **Use** tick, the run, its condition (T1 to T9), its repeat,
  one column per factor, and the cross-check result. You can untick a run to leave it out, type in a
  factor cell to override a level, double-click a column header to rename a factor, or right-click
  it for more options.
- **Add factor…** adds any field of `run_summary.xlsx` as a factor. **Leave out runs with no trial**
  drops side tests whose Notes name no trial. **Reset to detected** undoes every edit. Your edits are
  saved in the output folder (`taguchi_design.json`) and come back next time.
- The **findings list** under the table explains balance, orthogonality and replication, and what each
  means for the statistics.
- **Analyse** reads the measured runs and writes `taguchi_report.md`, `taguchi_analysis.xlsx` and
  `figures\` into the output folder, plus `csv\` and `odd\` if those were ticked on the Batch tab. It
  takes about a minute. **Open report** and **Open output folder** are beside it. The size bins come
  from the Settings tab.

**Tonight's design needs no edits:** check the banner and press **Analyse**.

**I3. For the Phase 11 timings**, copy this PC's measured speeds next to the job files:

```
copy "%USERPROFILE%\.hpatr\eta_calibration.json" "%LACIE%\Experiments\Taguchi\Taguchi_ReRun_2026-10-05\_job\"
```

Bring the LaCie back to the Mac and tell Claude there: *"fold in the Windows timings from
Taguchi_ReRun_2026-10-05"*.

---

## How the time estimate learns

- **Within a batch:** the ETA starts from built-in figures, then switches to what this batch has
  actually measured as soon as run 1 finishes.
- **Across batches on this PC:** after every real run, the measured time per stage is saved to
  `%USERPROFILE%\.hpatr\eta_calibration.json`, keeping the last 30 per stage. **Every later batch on
  this PC starts from its own measured speeds**, whatever the campaign, instead of the built-in
  figures. Inference is remembered separately per device (cuda or cpu), and the image stages per image
  mode. So the first batch you ever run with "every frame" ticked starts from the built-in figures for
  those stages, then learns them too.
- **Built-in figures for a new machine:** the copy in I3 lets the Mac session update the starting
  figures used on a PC with no history yet (or if that file is deleted).
- Test runs and the self-test never write to that file, so they can't spoil the estimates.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| Self-test says NOT READY | Do what each FAIL's `->` line says, then run it again. If you can't, don't start: save the output for the Mac session. |
| A black console window appears | Don't close it (closing it kills that stage); minimise it. The batch still works. Note it for the Mac session. |
| **Run batch** is greyed out | Hover over it: the tooltip says why. |
| Console says **stalled** | Some stages are quiet for a while. Wait 15 minutes. If it is still stalled, press **Stop now** and then **Resume**: the stuck run is redone. If it stalls again on the same run, Stop now, and bring the output folder's `_job` to the Mac session. |
| `CUDA out of memory` in a log | Close other GPU programs, then **Resume**. |
| The LaCie was unplugged and came back with a different letter | Give it its old letter back: Start, right-click, **Disk Management**, right-click the LaCie, **Change Drive Letter and Paths…**, **Change**, pick the old letter. Then **Resume**. |
| A run failed overnight | Morning: press **Retry failed (n)**. If it fails again, the reason is in its log under `_job\logs\`; bring `_job` to the Mac session. |
| Anything else | Stop the batch if it is misbehaving, save the output (below) and bring it to the Mac session. |

---

## Saving output for later

To keep the output of any command for the Mac session, run it again with this added at the end. It
writes a text file to your Desktop:

```
> "%USERPROFILE%\Desktop\taguchi_output.txt" 2>&1
```

For example, for the self-test:

```
"%PY%" -m src.ai.Taguchi_Analysis_UI --selftest > "%USERPROFILE%\Desktop\taguchi_output.txt" 2>&1
```

Everything about a batch is also kept on the LaCie, in the output folder's `_job\` folder
(`worker.log`, `logs\`, `events.jsonl`, `state.json`, `timings.csv`), so bringing the drive back to
the Mac is enough.
