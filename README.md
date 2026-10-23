# TEXT-TO-SPACESHIP V2

> **V2** builds on [V1](https://github.com/ss394/TTS-V1): a part-size slider with "find largest size that fits",
> modelled brackets in Stage 2 (simple ↔ metal 3D-printed, part of the packing and of the fit proof), an exploded
> view, a Mounting Hardware tab, two independent FEA solvers (CalculiX, NGSolve), a generative-design contest for
> 3D-printed brackets, 3U / 6U / 12U envelopes and optional parts — see [docs/V2.md](docs/V2.md). V2 runs on port
> 8766, so V1 and V2 can run side by side.

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

## Run it in your browser — any device (GitHub Codespaces)

1. On this repository's GitHub page click **Code → Codespaces → Create codespace on main**. You need a free GitHub account; it uses your Codespaces allowance.
2. Wait for the first setup to finish (several minutes: it installs Python 3.14, the packages and the user
   interface). Later starts are much faster.
3. The app starts by itself on port 8766. Open the **Ports** tab and click the globe next to
   **TEXT-TO-SPACESHIP** (it may also open on its own).
4. Stop the codespace when you are done, so it stops using your allowance.

Each codespace is a private copy: changes you make there do not affect anyone else.

## Run it on your own computer

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and [Node.js 24](https://nodejs.org/).
Download this repository (**Code → Download ZIP**, or `git clone`), then:

* **Windows:** double-click `start.cmd`.
* **macOS / Linux:** run `bash start.sh` in the folder.

The first start builds the interface and installs the Python packages (a few minutes). The app then opens at
<http://127.0.0.1:8766>. It only accepts connections from the same computer.

## Use your own parts

Drag STL files onto the window (or use **Add parts**) and confirm their units. Each new part is analysed and joins
the next search. `start.cmd --add part.stl` / `bash start.sh --add part.stl` queues files from the command line.

## Documentation

* [docs/V2.md](docs/V2.md) — what V2 adds; [docs/V2-GD-CONTEST.md](docs/V2-GD-CONTEST.md) — the bracket contest
* [docs/FINAL-REPORT.md](docs/FINAL-REPORT.md) — what is built and tested, key results, limitations, deferred work
* [docs/STATUS.md](docs/STATUS.md) — every measured number, deviations from the protocol
* [docs/api-contract.md](docs/api-contract.md) — REST and WebSocket interface
* [docs/PROTOCOL.md](docs/PROTOCOL.md) — the engineering protocol the project follows

## Tests

* Backend: `cd backend` then `uv run pytest`
* Front end: `cd frontend` then `npm ci`, `npm test` (unit) and `npx playwright test` (browser, mock backend)

## Licence

[MIT](LICENSE) © 2026 Sebastian Shunda. The Python and JavaScript packages that uv and npm install are not part of
this repository and keep their own licences.
