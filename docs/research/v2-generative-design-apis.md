# V2 research: commercial and cloud generative-design APIs (2026-10-22)

Research only (web and official documentation). Nothing was installed, signed up for or keyed. Autodesk Fusion 360 and
SolidWorks are excluded at the user's instruction. "TO" = topology optimisation with FEA in the loop; "Gen" = shape
generation without physics. Facts marked UNVERIFIED could not be confirmed from a primary source.

## Summary

| Tool | Kind | Automatable | What the user would need | Runs |
|---|---|---|---|---|
| Altair / Siemens Simcenter OptiStruct (+ Inspire) | TO, AM overhang constraint, non-design regions | batch solver; Inspire Python batch mode | Altair One account + Units licence (or Student Edition with OptiStruct confirmed), solver install, path given to the app | local |
| nTop + nTop Automate (nTopCL) | TO, passive regions | headless notebooks driven by JSON from Python | nTop + Automate licences (pricing not public), one login by the user, a TO notebook template | local (cloud licensing) |
| Ansys / Synopsys Mechanical via PyMechanical | TO (density-based), exclusion regions | PyMechanical (MIT) driving a licensed install | Mechanical licence with Structural Optimization, or Ansys Student (educational, 128 K nodes) | local |
| Hexagon MSC Apex Generative Design | stress-driven TO, non-design spaces | command-line engine on a GUI-exported scenario (config keys undocumented, UNVERIFIED) | Studio + Engine licences or MSCOne tokens | local |
| Zoo.dev Text-to-CAD | Gen only | REST + Python SDK | account + API token; **terms ban "benchmarking or competitive analysis"** and license inputs/outputs for model training | cloud upload |
| SimScale API | cloud FEA only (no TO) | REST + SDKs | paid plan | cloud upload |
| Onshape API | parameter-to-CAD, no TO | REST | paid plan (Free plan documents are public; yearly call caps) | cloud |
| Creo GTO / GDX, 3DEXPERIENCE generative roles | TO | no documented API (GUI only) | — | — |
| Siemens NX TO, Tosca, Abaqus LE | TO | API unverified / heavy licensing / 1,000-node cap | — | — |
| ParaMatters, OnScale, Physna, Backflip, Adam, ToffeeX, CDS | acquired, no API, or not TO | — | — | — |

## Decision for V2

None of the commercial tools can be used without the user's own licence or account, and the only cloud text-to-CAD
API forbids benchmarking in its terms. The V2 bracket contest therefore uses open-source generators that run locally;
the commercial ones are listed as optional entrants the user can enable later with their own licence (the app must
never handle their password). Local tools also avoid uploading spacecraft geometry (possible export-control
concerns; advisory, not sourced).

Sources: see the agent report in the session transcript; key links — nTop licensing
<https://docs.ntop.com/help-articles/access-and-installation/accounts-and-licensing/ntop-licensing-options>,
Inspire API <https://help.altair.com/inspire/inspireapi/index.html>, OptiStruct DTPL
<https://help.altair.com/hwsolvers/os/topics/solvers/os/dtpl_bulk_r.htm>, PyMechanical
<https://mechanical.docs.pyansys.com/version/stable/examples/index.html>, Ansys Student
<https://ansys.synopsys.com/academic/students/ansys-student>, Zoo terms <https://zoo.dev/terms-and-conditions>,
SimScale analysis types <https://www.simscale.com/docs/analysis-types/>, Onshape API limits
<https://onshape-public.github.io/docs/auth/limits/>.
