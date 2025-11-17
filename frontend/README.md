# How to run the frontend

## Development

Install dependencies via `npm install` in frontend folder.

Edit configurations in WebStorm:
- Add configuration:
    - Select `npm`
    - Scripts: `dev`
- Add configuration:
    - Select `JavaScript Debug`
    - URL: `http://localhost:5173`

## Production

Push code to github, pull down the latest version on the AWS server.
- Run `./scripts/deploy-to-s3.sh`