# Cotonou flight price tracker

Checks Google Flights every morning for return fares from Cotonou (COO), keeps the
price history, and sends a Telegram message when a fare is clearly cheaper than usual.
A dashboard with price charts is published on GitHub Pages.

## What it watches

Set in [`routes.yaml`](routes.yaml); edit that file to add or remove destinations.

- **Home visits** (3- and 4-week trips, up to 5 months ahead)
  - **Brussels**: nonstop, or a stop on the same plane (Brussels Airlines via Accra).
  - **Amsterdam**: the nonstop to Paris CDG plus a separate Paris–Amsterdam flight that
    leaves at least 2 hours (at most 6) after landing, and the same on the way back.
- **Holiday ideas** (2-week trips, up to 3 months ahead): Istanbul, Casablanca, Dakar,
  Abidjan. Nonstop or same-plane stop only.

A stop counts as "same plane" only when the flight continues under the same flight number.

### How trips are priced

Google Flights only shows round-trip prices to automated searches for a few very popular
routes (from Cotonou: just Paris), but one-way prices for most routes. So the tracker
searches one-way fares in each direction and pairs them into trips: a departure date plus
the cheapest return within 2 days of the wanted trip length. **A trip's price is the price
of two one-way tickets.** A return ticket can be cheaper, especially with Air France or
Brussels Airlines; every alert and dashboard entry links to Google Flights so you can check
the actual return fares. The "cheaper than usual" comparison is like-for-like, so it is not
affected.

Not tracked (checked October 2026): Accra and Douala (no direct flights shown, all change
in Lomé or Abidjan); Libreville, Malabo and Addis Ababa (Google shows no prices to
automated searches, even though they appear in a normal browser). Cotonou–Amsterdam is also not shown, hence the Paris construction.

Searched dates sit on a fixed calendar grid (every 3 days, both directions), so the same
dates are re-checked daily and every day of the week gets covered. That's about 430
searches per daily run (~35 minutes).

## When you get a message

- **Deal alert**: today's cheapest fare on a route is at least 15% below the usual
  cheapest fare (the median of the last 30 days), or a specific departure date is 15%
  below its own average. Alerts start after 7 days of history. The same trip is only
  re-sent if it drops another 5%.
- **Sunday overview**: the cheapest fare per destination and how it compares with usual.
- **Warning**: if more than half the searches fail (for example if Google blocks them).

## One-time setup

1. **Telegram bot.** In Telegram, open **@BotFather**, send `/newbot`, pick a name, and
   copy the token it gives you. Open your new bot and press **Start**. Then message
   **@userinfobot**; it replies with your numeric **Id**.
2. **Secrets.** In this repository: *Settings → Secrets and variables → Actions →
   New repository secret*. Add `TELEGRAM_BOT_TOKEN` (the token) and `TELEGRAM_CHAT_ID`
   (your Id).
3. **Dashboard.** *Settings → Pages → Build and deployment*: Source **Deploy from a
   branch**, branch **main**, folder **/docs**, Save.
4. **Test.** *Actions → Track flight prices → Run workflow*, choose **test-telegram**.
   You should get a Telegram message within a minute. Run it again with **track** to do
   the first real price check (about 35 minutes).

After that it runs by itself every day at 06:17 Cotonou time. The dashboard lives at
`https://<your-username>.github.io/cotonou-flight-tracker/`.

## Changing things

- Different trip length, more dates or new destinations: edit `routes.yaml`.
- Family total instead of per-person price: change `adults` in `routes.yaml`
  (child and infant prices would need a small code change in `tracker.py`).
- More or fewer alerts: change `deal_threshold` (0.15 = 15% below usual).

## Files

| File | What it is |
|---|---|
| `routes.yaml` | Routes and alert settings |
| `tracker.py` | Searches, history, alerts, dashboard |
| `dashboard_template.html` | Dashboard layout |
| `data/legs.csv` | Every one-way fare found, one row per route, direction, date and day checked |
| `data/runs.csv` | How each daily run went |
| `docs/index.html` | The generated dashboard |
| `.github/workflows/track.yml` | The daily schedule |

`python tracker.py --simulate 40` fakes 40 days of prices into `_sim/` to try changes
without internet access. `diagnose.py` runs a few live searches on GitHub and writes
`data/diagnostics.txt` (Actions → Run workflow → diagnose).

Prices come from Google Flights via the open-source
[fast-flights](https://github.com/AWeirdDev/flights) library, which reads the public
Google Flights page. If Google changes that page, the searches can start failing until
the library is updated.
