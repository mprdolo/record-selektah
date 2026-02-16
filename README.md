# Record Selektah

A personal vinyl listening companion that connects to your [Discogs](https://www.discogs.com) collection, randomly selects records for you to listen to, tracks your play history, and optionally integrates with a personal album ranking list (the "Big Board").

Inspired by reggae sound system DJs ("selektahs") of the 1960s-70s.

<!-- ![Record Selektah screenshot](screenshot.png) -->

## Features

- **Random Selection** -- Pick a record at random from your collection and mark it as Played, Skipped, or Excluded
- **The Library** -- Browse your full Discogs collection sorted by artist, title, or year
- **Listening Stats** -- See your most-played albums ranked by play count
- **Big Board Explorer** -- View your personal album ranking by rank, decade, genre, or as a heatmap
- **Excluded Albums** -- Manage albums removed from the random selection pool
- **Album Detail Cards** -- View metadata, genres, styles, play counts, and Discogs links for any album
- **Master Release Overrides** -- Manually set or correct master release links for accurate year data

## Setup

### Prerequisites

- Python 3.12+
- pip
- A [Discogs](https://www.discogs.com) account with a collection

### Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/YOUR_USERNAME/record-selektah.git
   cd record-selektah
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file from the example:

   ```bash
   cp .env.example .env
   ```

4. Open `.env` and set your Discogs credentials:

   ```
   DISCOGS_TOKEN=your_token_here
   DISCOGS_USERNAME=your_username
   ```

   Generate a personal access token at [discogs.com/settings/developers](https://www.discogs.com/settings/developers).

5. Run the app:

   ```bash
   python app.py
   ```

   Open `http://localhost:3345` in your browser.

## Syncing Your Collection

Click **Sync Data** in the header, then choose **"Sync Discogs Collection"**. This imports every release from your Discogs collection. Re-sync any time to pick up additions or removals.

## Big Board (Optional)

The Big Board is your personal album ranking -- any list of albums ranked by preference.

### CSV Format

Create a CSV file with 4 columns and place it at `data/big_board.csv`:

```csv
Artist,Title,Year,Owned
Radiohead,OK Computer,1997,x
Miles Davis,Kind of Blue,1959,
Talking Heads,Remain in Light,1980,x
```

- Rows are ordered by rank (row 1 = #1, row 2 = #2, etc.)
- Mark `x` in the **Owned** column for albums you own; leave blank otherwise

### Importing

Click **Sync Data** > **"Import Big Board CSV"**. Unmatched entries can be manually linked to your collection in the Big Board Explorer.

## Fetching Master Years (Optional)

Click **Sync Data** > **"Fetch Master Release Years"** to backfill original release years from Discogs master releases. This ensures albums display the original year rather than the year of your specific pressing.

## Usage

| Section | What it does |
|---------|-------------|
| **Home** | Click "Select Next Record" for a random pick. Mark as Played, Skip, or Exclude. |
| **Big Board** | Browse your ranked list by rank tiers, decades, genres, or as a heatmap. |
| **Library** | Browse your full collection with sort and search. |
| **Stats** | View most-played albums by play count. |
| **Excluded** | Manage albums excluded from random selection. |

## Tech Stack

- **Backend:** Flask, SQLite
- **Frontend:** Vanilla JavaScript, HTML, CSS
- **Data Source:** Discogs API

## Credits

Created by [M. Palma](https://palmaradio.substack.com) at Public Diplomacy Records.
