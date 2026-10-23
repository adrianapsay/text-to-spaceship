# V2 research: 3U / 6U / 12U CubeSat envelopes

Research agent report, 2026-10-22. The 3U values the app already uses match CDS Rev 14.1 exactly. Rev 14.1 also covers
6U and 12U and supersedes the 6U CDS Rev 1.0. Values marked UNVERIFIED were not confirmed in a primary document.

## Adopted (CDS Rev 14.1, Cal Poly CP-CDS-R14.1, Feb 2022)

| | X × Y × Z (rail envelope) | Rails | Side protrusion | CoG box ("shall") | Mass ("Note") |
|---|---|---|---|---|---|
| 3U | 100.0 × 100.0 × 340.5 mm | 4 corner, ≥ 8.5 mm | ≤ 6.5 mm | ±20 / ±20 / ±70 mm | 6.00 kg |
| 6U | **226.3 × 100.0 × 366.0 mm** (±0.1) | 4 corner only, no mid-face rails | ≤ 6.5 mm (6U CDS 1.0 allowed 10) | **±45 / ±20 / ±70 mm** | 12.00 kg |
| 12U | **226.3 × 226.3 × 366.0 mm** (±0.1) | 4 corner only | ≤ 6.5 mm | **±45 / ±45 / ±70 mm** | 24.00 kg |

Sources: [CDS Rev 14.1](https://www.nasa.gov/wp-content/uploads/2018/01/cubesatdesignspecificationrev14_12022-02-09.pdf)
drawings CDS-14-004 (3U), -007 (6U), -008 (12U), §2.2.1–2.2.11 (shall / should / note per §1.6);
[6U CDS Rev 1.0](https://s3vi.ndc.nasa.gov/ssri-kb/static/resources/6U_CDS_2018-06-07_rev_1.0.pdf) (superseded).

The 226.3 mm axis is X (matches the ±45 mm X CoG limit).

## Deployer differences (context)

* **Length:** rail-deployer vendors call 340.5 mm "standard" and ≈ 366 mm "XL"; the CDS 6U / 12U length is the XL
  slot. Some slots are 340.5 mm only (Astrofein PSL6U, Exolaunch standard, UARX standard).
* **PSC / Rocket Lab CSD** (tab-based, no rails): 6U dynamic envelope ≈ 239 × 116 × 366 mm, 12U ≈ 239 × 229 × 366;
  no mass limit (tab load ≤ 3559 N); CoM in the PSC payload frame — not comparable with the CDS box.
  ([PSC 2002367F](https://www.rocketlabusa.com/assets/Uploads/PSC/Rocket%20Lab%20PSC%20-%202002367F%20Payload%20Spec%20for%203U%206U%2012U.pdf))
* **Exolaunch EXOpod Nova:** 6U 14.0 kg / 6U XL 16.0 kg; 12U 26.0 kg; protrusions up to 39.5 mm; CoG ±45/±20/±70
  as a guideline. ([manual](https://www.exolaunch.com/documents/EXOpod_Nova_User_Manual_June_2024.pdf))
* **UARX RAMI 12U (2022):** CoG ±20 / ±20 / ±70 — tighter than the CDS. 24 kg (30 kg in the 2025 revision).
* NanoRacks NRCSD 6U is the 1 × 6 long form, not this form factor. Tyvak, Rocket Lab Maxwell, Astrofein 12U: UNVERIFIED.

## Internal envelope

Neither the CDS nor any deployer defines a CubeSat's internal envelope. The app keeps its 3U frame model (2 mm walls,
solid 8.5 mm corner rails — conservative: real rails are L-profiles) and applies the same rules to 6U / 12U: inner
box = envelope − 2 × 2 mm walls in X and Y and the same end-plate allowance in Z as 3U. ASSUMED, configurable later.

PC/104 boards are 90.17 × 95.89 × 1.57 mm, 15.24 mm pitch ([PC/104 v2.6](https://pc104.org/wp-content/uploads/2015/02/PC104_Spec_v2_6.pdf)).

## Caveats shown in the app

1. 366 mm 6U / 12U needs an XL slot on some deployers.
2. The UARX 2022 12U CoG box is tighter than the CDS box.
3. PSC CSD payloads use a different origin and CoM frame.
