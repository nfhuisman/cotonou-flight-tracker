# Cotonou flight price tracker

Checks Google Flights every morning for return fares from Cotonou (COO), keeps the
price history, and sends a Telegram message when a fare is clearly cheaper than usual.
A dashboard with price charts is published on GitHub Pages.

## What it watches

Set in [`routes.yaml`](routes.yaml); edit that file to add or remove destinations.

- **Home visits**: Brussels (nonstop or same-plane stop) and Amsterdam (via Paris CDG with a
  change of 2–6 hours), each for 3- and 4-week trips, up to 5 months ahead.
- **Holiday ideas**: Istanbul, Casablanca, Addis Ababa, Dakar, Abidjan, Accra,
  Libreville, Douala, Malabo. Two-week trips, up to 4 months ahead, nonstop or
  same-plane stop only.

Departure dates sit on a fixed calendar grid (every 4 days for home visits, every 6 for
holidays), so the same dates are re-checked daily and, over a few weeks, every day of the
week is covered. That's about 315 searches per daily run.

A "same-plane stop" is a best guess: one airline, same aircraft type, stop under
2.5 hours. Check the itinerary before booking.

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
   the first real price check (about 15–25 minutes).

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
| `data/prices.csv` | Every fare found, one row per route, date and day checked |
| `data/runs.csv` | How each daily run went |
| `docs/index.html` | The generated dashboard |
| `.github/workflows/track.yml` | The daily schedule |

`python tracker.py --simulate 40` fakes 40 days of prices into `_sim/` to try changes
without internet access.

Prices come from Google Flights via the open-source
[fast-flights](https://github.com/AWeirdDev/flights) library, which reads the public
Google Flights page. If Google changes that page, the searches can start failing until
the library is updated.
