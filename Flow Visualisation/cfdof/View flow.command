#!/bin/bash
# Double-click to open this CFD case in ParaView: your newest saved view (a .pvsm saved into this folder) if there is
# one, else the case at its last iteration, as CfdOF's Paraview button opens it.
# Keep a copy in each case's folder, ~/OpenFOAM/cfdof_cases/<case>/, beside its case/ folder (CFDOF_GUIDE.md, 8.1).
here="$(cd "$(dirname "$0")" && pwd)"
app="$(ls -d /Applications/ParaView*.app 2>/dev/null | tail -1)"
state="$(ls -t "$here"/*.pvsm 2>/dev/null | head -1)"
if [ -z "$app" ]; then
  echo "No ParaView in /Applications."
elif [ -n "$state" ]; then
  open -n -a "$app" --args --state="$state"
  exit 0
elif [ -f "$here/case/pvScript.py" ]; then
  # CfdOF's script names the case as 'pv.foam' from inside case/; ParaView starts elsewhere, so give it the full path
  script="$(mktemp -d)/view.py"
  sed "s|r'pv.foam'|r'$here/case/pv.foam'|" "$here/case/pvScript.py" > "$script"
  open -n -a "$app" --args --script="$script"
  exit 0
else
  echo "Nothing to open in $here: no saved view (.pvsm) and no CfdOF case yet (case/pvScript.py: CfdOF writes it at Write)."
fi
read -n 1 -s -r -p "Press any key to close."
