# JP

## GitHub Pages Deployment

This repo is configured to deploy automatically to GitHub Pages from `main`.

### One-time setup

1. Push this repository to GitHub.
2. In GitHub: `Settings` -> `Pages`.
3. Under `Build and deployment`, set `Source` to `GitHub Actions`.
4. Push any commit to `main` (or run the `Deploy GitHub Pages` workflow manually).

After deployment, your site will be available at:
`https://<your-username>.github.io/<your-repo>/`

### Local Pages build check

```bash
python scripts/build_pages.py
python -m http.server --directory site 8000
```

## In-House Ops Dashboard

The custom Python booking system now includes a staff-only operations view at:
`/ops/`

Use it to:
- search client records
- save preferred barber/style notes
- review visit history
- complete checkout and capture collected amount
- monitor high-level revenue and missed-visit metrics

Staff access:
- log in through Django admin at `/admin/`
- then open `/ops/`

## Booksy External Calendar Import Setup

Use this when importing in-house bookings into Booksy as an external calendar.

1. Log in as a staff/admin user in this app.
2. Download the calendar file from:
   `/api/admin/bookings/export.ics`
3. In Booksy, follow:
   `Profile -> Booking settings -> Add external calendar`
4. Upload the downloaded `.ics` file.

Notes:
- The export includes active booking-blocking records (`confirmed`, `rescheduled`, `completed`, `missed`) and excludes `cancelled`.
- Keep imports within Booksy limits (about current-month start, up to 2 years ahead, and up to ~6 months back).
