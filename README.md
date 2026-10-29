# TEXT-TO-SPACESHIP V3

> **V3** adds the **CubeSat Builder** to V2: from a mission idea to an engineering-informed CubeSat design (adaptive
> mission questions, subsystem sizing with traceable equations, real components with sources, CAD, compatibility
> checks) and on into V2's packing optimiser — see [docs/V3.md](docs/V3.md). V3 runs on port 8768, so V1 (8765),
> V2 (8766) and V3 can run side by side.
>
> **V2** builds on [V1](https://github.com/ss394/TTS-V1): a part-size slider with "find largest size that fits",
> modelled brackets in Stage 2 (simple ↔ metal 3D-printed, part of the packing and of the fit proof), an exploded
> view, a Mounting Hardware tab, two independent FEA solvers (CalculiX, NGSolve), a generative-design contest for
> 3D-printed brackets, 3U / 6U / 12U envelopes and optional parts — see [docs/V2.md](docs/V2.md).

A physics-aware packaging optimiser for a 3U CubeSat (6U and 12U in V2). Give it any STL parts: it analyses and
classifies them, packs them into the 100 × 100 × 340.5 mm envelope (or the 6U / 12U one) with several search algorithms, certifies every reported layout on the
exact meshes (with an independently checkable proof), computes mass properties and inertia, and explains which
algorithm it chose and why. Sliders change the priorities live.

* **Stage 1 — IDEALIZED:** geometry-only packing.
* **Stage 2 — ENGINEERING-CONSTRAINED:** an ASSUMED frame, rails, clearances, PC/104 stack, mounting and harness
  rules. Not flight-qualified.
* **Manufacturable Design:** brackets for every part, including conformal metal 3D-printed ones (marked "AM"), with
  a relative cost model (a concept, not a quote; not stress-analysed).
* **FUSION 360 VALIDATION: NOT CONFIGURED.** The app prepares an export package but never calls Fusion 360.

## Run it on a Windows PC

1. Download this repository: **Code → Download ZIP** on its GitHub page, and unzip it into a short path such as
   `C:\TTS-V3` (or `git clone` it).
2. Double-click **`setup.cmd`**. It lists what it will download, asks, then puts everything inside the folder:
   - uv, Node.js and CPython;
   - the Python and JavaScript packages pinned in the lock files;
   - CalculiX and BESO.

   Each file comes from its official site and is checked against the hash recorded in the repository. It needs no
   administrator rights and writes nothing to the registry or your user profile. It takes about 2.5 GB, and the first
   run takes several minutes. At the end it offers to fetch the makers' CAD (see below).
3. Double-click **`start.cmd`**. The app opens at <http://127.0.0.1:8768>; only this computer can reach it.

If Windows warns that a script comes from the internet, choose **Run** (or **More info → Run anyway**). Running
`setup.cmd` again, for example after an update, checks what is already in place and keeps it.

## Run it on a Mac (Apple silicon: M1 or later)

1. Download or `git clone` this repository.
2. In Terminal, in the folder, run **`bash setup.sh`**. It does what `setup.cmd` does on Windows, with the Mac builds of
   the same tools: uv, Node.js and CPython 3.14.8, the pinned Python and JavaScript packages, CalculiX 2.23 and BESO.
   Each file is checked against the hash recorded in the repository, and everything stays inside the folder.
3. Run **`bash start.sh`**. The app opens at <http://127.0.0.1:8768>.

Intel's MKL, whose PARDISO solver the optimisers use on Windows, has no Mac build: on a Mac they use a sparse
Cholesky solver instead, with the same results to round-off ([docs/V3.md §5.6](docs/V3.md)). It is about half as
fast on macOS 15 or later (CHOLMOD) and much slower on older versions (NGSolve), so an optimisation with the same
time budget gets fewer iterations.

## Run it on Linux

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and [Node.js 24](https://nodejs.org/). Run
`bash start.sh` in the folder. The first start installs the Python packages and builds the interface, which takes a
few minutes. CalculiX is set up on Windows and macOS only; without it the FEA runs on NGSolve alone.

## Run it in your browser — any device (GitHub Codespaces)

1. On this repository's GitHub page click **Code → Codespaces → Create codespace on main**. You need a free GitHub
   account; it uses your Codespaces allowance.
2. Wait for the first setup to finish. It takes several minutes, because it installs Python 3.14, the packages and the
   user interface; later starts are much faster.
3. The app starts by itself on port 8768. Open the **Ports** tab and click the globe next to
   **TEXT-TO-SPACESHIP** (it may also open on its own).
4. For the makers' CAD, run `bash get-cad.sh` in the codespace's terminal.
5. Stop the codespace when you are done, so it stops using your allowance.

Each codespace is a private copy: changes you make there do not affect anyone else.

## The makers' CAD

The Builder uses the makers' own CAD for 14 of its parts ([docs/V3.md §5.4](docs/V3.md)): in its 3D preview, in its
checks and when a design is sent to the optimiser. Those files belong to their makers, so they are not in this
repository. **`get-cad.cmd`** (`bash get-cad.sh` on macOS, Linux and Codespaces) fetches and imports them:
1. It lists the files and asks before downloading.
2. It downloads each file from its maker's website (148.7 MB in all).
3. It checks each file's SHA-256 against the one recorded here.
4. It imports each file through the app's checks, so you get the same STL models as the computer they were first
   imported on.

`--list` lists the files, and `--only PART` takes only some of them.

Already have the files on another computer? Copy its `data\builder\cad\downloads` folder over and run
`get-cad.cmd --from <that folder>` (`bash get-cad.sh --from <that folder>` on a Mac): nothing is downloaded.

## Bring your work from another computer

Your work is not in the repository; it lives in two folders under `data`:
* `data\builder`: your Builder designs and the imported CAD with its STL files;
* `data\projects`: your optimiser projects.

Stop the app on both computers, then copy those two folders into the new copy's `data` folder.

## Use your own parts

Drag STL files onto the window (or use **Add parts**) and confirm their units. Each new part is analysed and joins
the next search. `start.cmd --add part.stl` / `bash start.sh --add part.stl` queues files from the command line.

## Documentation

* [docs/V3.md](docs/V3.md) — the CubeSat Builder: how it works, its tests, its limits and the makers' CAD
* [docs/V2.md](docs/V2.md) — what V2 adds; [docs/V2-GD-CONTEST.md](docs/V2-GD-CONTEST.md) — the bracket contest
* [docs/FINAL-REPORT.md](docs/FINAL-REPORT.md) — what is built and tested, key results, limitations, deferred work
* [docs/STATUS.md](docs/STATUS.md) — every measured number, deviations from the protocol
* [docs/api-contract.md](docs/api-contract.md) — REST and WebSocket interface
* [docs/PROTOCOL.md](docs/PROTOCOL.md) — the engineering protocol the project follows

## Tests

* Backend: `cd backend` then `uv run pytest`
* Front end: `cd frontend` then `npm ci`, `npm test` (unit) and `npx playwright test` (browser, mock backend)

## Licence

[MIT](LICENSE) © 2026 Sebastian Shunda. The Python and JavaScript packages that uv and npm install, the tools that
`setup.cmd` fetches and the makers' CAD that `get-cad` fetches are not part of this repository and keep their own
licences.
