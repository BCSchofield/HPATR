# Backing up the LaCie (2026-10-26, Mac; to be done on the home PC)

**State: there is no backup of the LaCie.** It holds the only copy of every capture, and it drops off USB on the
home PC (STATUS, Machines). This note is the plan, the measured sizes, and the exact FreeFileSync setup, written on
the Mac for Claude Code on the home PC (BENS-PC, LaCie = `D:`) to pick up.

**Rules:**
- The LaCie is only ever *read*. FreeFileSync goes LaCie → backup with **Mirror**, never **Two way**, which would
  copy changes on the backup back onto the LaCie. FreeFileSync may leave a small temporary `sync.ffs_lock` at the
  top of `D:\` during a run; it never touches the capture folders.
- The CLAUDE.md rule stands: never modify raw data on the LaCie.

## What is on it (measured 2026-10-26 on the Mac, read only)

`df`: 4.5 TiB drive, 2.1 TiB used, 2.4 TiB free. Sizes below are GiB, which Windows and FreeFileSync also show as "GB".

| What | Size | Files | Notes |
|---|---|---|---|
| Run `.cine` (`Experiments\2026\<mm>\<dd>\<run>\shadowgraph\raw\CINE\`) | 1,357 GB | few | Raw. One CCD-day `.cine` is 15 GB. |
| Run frames (`...\shadowgraph\raw\frames\8bit`, `16bit`) | 254 GB | 82,472 | Every 10th frame, TIFF/PNG only. All 83 frames folders have their `.cine`, so re-extractable; `extraction_metadata.json` (outside `frames\`) records which. |
| Run analysis (`...\shadowgraph\analysis\`) | 60 GB | | GPU hours to redo. |
| The rest of `Experiments\2026` | ~167 GB | | **Not identified yet** (older run layouts? other files). Check first, command below. |
| `Calibration` | 105 GB | 4,424 | Calibration captures. |
| `Experiments\AI` | 48.5 GB | 3,756 | Models and checkpoints. |
| `Experiments\Taguchi` | 44.6 GB | 13,994 | Campaign outputs, CCD remeasure. |
| `Experiments\TrainingData` | 41.4 GB | 47,450 | Training images and labels. |
| `$RECYCLE.BIN` | 39 GB | 18,421 | Already deleted. Never backed up. |
| `Experiments\Real_Data` | 27.4 GB | 55,759 | Hand-labelled validation sets (06, 06_run2, 07, 09). |
| `Misc`, `Phantom`, `BackUps` | 22 GB | | |
| Everything else (`Validation_100`, `Lamella`, `Logs`, `Sandbox`, `Shadowgraph`, ...) | ~5 GB | | |
| Mac clutter (`._*`, `.Spotlight-V100`, `.fseventsd`, ...) | tiny | ~46,000 | |

Seven folders called `frames` are NOT run frames and must be backed up: `Real_Data\06_validation\frames`,
`06_validation_run2\frames`, `07_validation_taguchi\frames`, `09_experiments\02_Chosen_Frame\frames`,
`09_experiments\20_new_frames\frames`, `Taguchi\CCD\CCD sizer 3.1.0 remeasure 17-10-2026\frames`,
`Taguchi\9x3 Taguchi Repeats (sizer 2.2.0)\sharpness_review\frames`. The filter `*\shadowgraph\raw\frames\` only
matches the run ones.

**Growth:** October alone added 1.4 TB. A run is ~19 GB (`.cine` + frames + analysis), so 2.4 TiB free is ~135 runs,
about **4–5 more big rig days**.

## The plan: three copies

1. **The LaCie:** the working drive.
2. **A 16–20 TB desktop external drive** (mains-powered) for the full mirror. Not a second 5 TB LaCie: it would fill
   at the same moment. 16 TB holds this LaCie and the next working drive.
3. **University research storage** as the copy kept elsewhere. Ask the research data / IT service. Upload on campus
   over a wired connection; 2 TB over home broadband takes days.

**When the LaCie fills:** retire it as read-only "volume 1" and buy a new working drive ("volume 2"). The big backup
drive holds both in their own folders: add a second folder pair to the same FreeFileSync batch job.

## Step 1 (now): the interim backup to Ben's 1 TB drive

Everything except the run `.cine` and frames: about **520 GB**. That's the work that is hard to redo (labels,
training data, models, analysis, calibration). The `.cine` files wait for the big drive.

### 1a. Check space, and identify the unknown 167 GB

Run PowerShell **as administrator**:
```
Get-Volume | Where-Object DriveLetter | Select-Object DriveLetter, FileSystemLabel, FileSystem, @{n='SizeGB';e={[math]::Round($_.Size/1GB)}}, @{n='FreeGB';e={[math]::Round($_.SizeRemaining/1GB)}}
```
- The 1 TB drive shows as ~931 GB. It needs **~550 GB free** and must be **NTFS or exFAT**, not FAT32: some
  calibration captures are over 4 GB.
- If it has less free space, use the drop list below.

Then see what the unidentified ~167 GB in the run folders is. This is slow, minutes, and only reads:
```
Get-ChildItem D:\Experiments\2026 -Recurse -File -Force | Where-Object { $_.FullName -notmatch '\\shadowgraph\\raw\\(CINE|frames)\\' -and $_.FullName -notmatch '\\shadowgraph\\analysis\\' -and $_.Name -notlike '._*' } | Group-Object Extension | Select-Object Name, Count, @{n='GB';e={[math]::Round(($_.Group | Measure-Object Length -Sum).Sum/1GB,1)}} | Sort-Object GB -Descending | Select-Object -First 15
```
If it is mostly `.cine` (older runs laid out differently), those are raw data. Then decide with Ben whether they go
on the 1 TB drive or wait for the big one.

**If space is short, drop in this order (least costly to lose first):**
1. `Misc`, `Phantom`, `BackUps` (22 GB): check with Ben what they are.
2. `Experiments\AI` (48.5 GB): models, which can be retrained, though it takes days. Keep the final models if possible.
3. `Calibration` (105 GB): can be re-captured, but not that day's setup.

Never drop `Real_Data`, `TrainingData`, `Validation_100`, `Taguchi` or the run analysis folders. To drop a folder,
add it to the Exclude box, e.g. `\Experiments\AI\`.

### 1b. Stop sleep and USB suspend for the run (PowerShell as administrator)

```
powercfg /change standby-timeout-ac 0
powercfg /setacvalueindex SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0
powercfg /setactive SCHEME_CURRENT
```
Turning off USB selective suspend is a common fix for USB drives dropping off. Plug both drives straight into USB 3
ports, not a hub. Afterwards, restore sleep with `powercfg /change standby-timeout-ac 30`.

### 1c. The backup folders

Set `$B` to the backup drive's letter:
```
$B = 'E'
New-Item -ItemType Directory -Force "${B}:\LaCie_backup", "${B}:\LaCie_versions"
```

### 1d. FreeFileSync (free, freefilesync.org)

- **Folders:** left `D:\`, right `E:\LaCie_backup`.
- **The gear next to Compare,** Comparison tab: **File time and size**.
- **The funnel, Filter tab:** Include `*`. Replace everything in the **Exclude** box with:
  ```
  \System Volume Information\
  \$RECYCLE.BIN\
  *\shadowgraph\raw\CINE\
  *\shadowgraph\raw\frames\
  ```
  A trailing `\` means folders only; a leading `*` means at any depth. Matching ignores capitals.
- **The gear next to Synchronize,** Synchronization tab: **Mirror**. Deletion handling **Versioning**, folder
  `E:\LaCie_versions`, naming **Time stamp [Folder]**. With Versioning, anything Mirror would delete or overwrite on
  the backup (say after an exFAT glitch on the LaCie) is moved aside, not lost.
- **Compare.** The bottom bar should show ~520 GB, all copies to the right. If it shows ~2 TB, the filter didn't
  apply.
- **File → Save**, to keep this setup for later Compares.
- **Run it:**
  - Click **Synchronize** if Ben is nearby.
  - For unattended runs: **File → Save as batch job…**, tick **Ignore errors**, leave Auto-close off, save to the
    Desktop, then double-click it.
- Expect roughly 1.5–3 h. Most of it is the ~100,000 small files.

### 1e. Afterwards

- Open the saved setup and **Compare**: "nothing to synchronize" means it is complete.
- Restore sleep (above).
- If the LaCie dropped off at any point, repair it, then run the sync again:
  ```
  chkdsk D: /f
  ```

## Step 2: the big drive

- **Buy:** a 16 or 20 TB **desktop** external (October 2026):
  - **WD Elements Desktop** is the pick: CMR reported at 8 TB and up, 2-year warranty in the US. WD My Book is
    similar and usually dearer.
  - **Seagate Expansion Desktop** is often the cheapest per TB, with a shorter warranty in some regions.
  - **Avoid:** portable drives, 4–8 TB desktop models (often SMR, worse per TB), refurbished drives.
- **Price:** 16 TB was seen from ~€20 to ~$43 per TB depending on sales. Black Friday is 2026-11-27. Weigh waiting
  against a month with the `.cine` files backed up nowhere.
- **Format:** check it with `Get-Volume`. NTFS is right for a backup written only from Windows; it has a journal and
  the Mac can still read it. If it is anything else, it must be empty before reformatting, so ask Ben first.
- **Full mirror:** the same setup with the right side on the big drive, `X:\LaCie_backup` plus `X:\LaCie_versions`.
  Exclude **only**:
  ```
  \System Volume Information\
  \$RECYCLE.BIN\
  ```
  That is ~2.1 TB, 5–7 h on USB 3, so run it overnight as a batch job. After that, re-run the batch job whenever data
  is added; only changes are copied.

## Open: lossless compression of the `.cine`

Shadowgraph frames are mostly flat background, so the `.cine` files may compress well losslessly (bit-identical when
restored). If it is 2–3×, the archive copies need far less space. Not yet measured: the test on the Mac was cut short
when the LaCie was unplugged.

Test on a 500 MB chunk from the middle of two `.cine` files (read only, written to the PC's own disk), e.g. with
7-Zip or Python's built-in `lzma`. Report the ratio and the time per GB.
