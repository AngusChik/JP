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
