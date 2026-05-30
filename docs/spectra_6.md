# Inky Impression — Spectra 6

## Example: Drawing Shapes and Text with PIL

This basic example shows how to draw shapes and text on Inky Impression using PIL.

```python
# This basic example shows how to draw shapes and text on Inky Impression using PIL.

from font_fredoka_one import FredokaOne
from PIL import Image, ImageDraw, ImageFont

from inky.auto import auto

inky_display = auto(ask_user=True, verbose=True)

# Create new PIL image with a white background
image = Image.new("P", (inky_display.width, inky_display.height), inky_display.WHITE)
draw = ImageDraw.Draw(image)

font = ImageFont.truetype(FredokaOne, 72)

# draw some shapes
draw.rectangle((50, 50, 200, 200), fill=inky_display.YELLOW)  # Rectangle
draw.ellipse((150, 150, 300, 300), fill=inky_display.RED)  # Circle (ellipse)
draw.line((0, 0, 400, 400), fill=inky_display.BLUE, width=10)  # Diagonal line

# draw some text
draw.text((0, 0), "Hello, World!", inky_display.BLACK, font)

inky_display.set_image(image)
inky_display.show()
```

## Example: Reading Buttons with gpiod

```python
#!/usr/bin/env python3

import gpiod
import gpiodevice
from gpiod.line import Bias, Direction, Edge

print(
    """buttons.py - Detect which button has been pressed

This example should demonstrate how to:
 1. set up gpiod to read buttons,
 2. determine which button has been pressed

Press Ctrl+C to exit!

"""
)

# GPIO pins for each button (from top to bottom)
# These will vary depending on platform and the ones
# below should be correct for Raspberry Pi 5.
# Run "gpioinfo" to find out what yours might be.
#
# Raspberry Pi 5 Header pins used by Inky Impression:
#    PIN29, PIN31, PIN36, PIN18.
# These header pins correspond to BCM GPIO numbers:
#    GPIO05, GPIO06, GPIO16, GPIO24.
# These GPIO numbers are what is used below and not the
# header pin numbers.

SW_A = 5
SW_B = 6
SW_C = 16  # Set this value to '25' if you're using a Impression 13.3"
SW_D = 24

BUTTONS = [SW_A, SW_B, SW_C, SW_D]

# These correspond to buttons A, B, C and D respectively
LABELS = ["A", "B", "C", "D"]

# Create settings for all the input pins, we want them to be inputs
# with a pull-up and a falling edge detection.
INPUT = gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP, edge_detection=Edge.FALLING)

# Find the gpiochip device we need, we'll use
# gpiodevice for this, since it knows the right device
# for its supported platforms.
chip = gpiodevice.find_chip_by_platform()

# Build our config for each pin/line we want to use
OFFSETS = [chip.line_offset_from_id(id) for id in BUTTONS]
line_config = dict.fromkeys(OFFSETS, INPUT)

# Request the lines, *whew*
request = chip.request_lines(consumer="spectra6-buttons", config=line_config)


# "handle_button" will be called every time a button is pressed
# It receives one argument: the associated gpiod event object.
def handle_button(event):
    index = OFFSETS.index(event.line_offset)
    gpio_number = BUTTONS[index]
    label = LABELS[index]
    print(f"Button press detected on GPIO #{gpio_number} label: {label}")


while True:
    for event in request.read_edge_events():
        handle_button(event)
```

## Example: Rendering an Image File

```python
#!/usr/bin/env python3

import argparse
import pathlib
import sys

from PIL import Image

from inky.auto import auto

parser = argparse.ArgumentParser()

parser.add_argument("--saturation", "-s", type=float, default=0.5, help="Colour palette saturation")
parser.add_argument("--file", "-f", type=pathlib.Path, help="Image file")

inky = auto(ask_user=True, verbose=True)

args, _ = parser.parse_known_args()

saturation = args.saturation

if not args.file:
    print(f"""Usage:
    {sys.argv[0]} --file image.png (--saturation 0.5)""")
    sys.exit(1)

image = Image.open(args.file)
resizedimage = image.resize(inky.resolution)

try:
    inky.set_image(resizedimage, saturation=saturation)
except TypeError:
    inky.set_image(resizedimage)

inky.show()
```

## Example: Colour Bands

```python
#!/usr/bin/env python3

from inky.auto import auto

inky = auto(ask_user=True, verbose=True)

COLOURS = [0, 1, 2, 3, 5, 6]

for y in range(inky.height - 1):
    c = min(y // (inky.height // 6), 5)
    for x in range(inky.width - 1):
        inky.set_pixel(x, y, COLOURS[c])

inky.show()
```

## Example: Random Comic Cover from Comic Vine API

```python
"""
Python script to fetch a randomised comic cover from the Comic Vine API and show it on an Inky Impression display.
You will need to sign up for an API key at https://comicvine.gamespot.com/api/ to use this script.
Change the search query to the comic series you want to display!
"""

import random
from io import BytesIO

import requests
from PIL import Image

from inky.auto import auto

# Comic Vine API details
API_KEY = "API_KEY_GOES_HERE"
BASE_URL = "https://comicvine.gamespot.com/api/"
HEADERS = {"User-Agent": "Python Comic Vine Client"}

# List of comic series to display, separated by commas. You can add more series to this list, or change the existing ones.
SEARCH_QUERIES = ["Weird Science"]
# Set to True to pick a random volume from the query results (this is helpful if the series is split into multiple volumes):
RANDOM_VOLUME = False

# Inky Impression display setup
inky_display = auto()


def find_volume_id(api_key, query):
    # Our first API call finds a list of volumes that match the search query, and then picks one
    params = {"api_key": api_key, "format": "json", "query": query, "resources": "volume", "limit": 5}
    response = requests.get(f"{BASE_URL}search/", headers=HEADERS, params=params)
    response.raise_for_status()
    data = response.json()
    response.close()
    results = data.get("results", [])
    if results:
        for idx, volume in enumerate(results, 1):
            print(f"{idx}: {volume['name']} (ID: {volume['id']}, Start Year: {volume.get('start_year', 'N/A')})")

        if RANDOM_VOLUME is True:
            # Pick a random volume from the search results
            chosen = random.choice(results)
            print(f"Randomly selected: {chosen['name']} (ID: {chosen['id']})")
        else:
            # Pick the first volume from the search results
            chosen = results[0]
            print("Picked first result!")
        return chosen["id"]
    else:
        raise ValueError("No volumes found for the given query.")


def fetch_random_comic_image(api_key, series_id):
    # Once we know the volume ID we can do a second API call to fetch a list of issues and pick a random cover image
    params = {"api_key": api_key, "format": "json", "filter": f"volume:{series_id}", "limit": 100}
    response = requests.get(f"{BASE_URL}issues/", headers=HEADERS, params=params)
    response.raise_for_status()
    data = response.json()
    response.close()
    results = data.get("results", [])
    if results:
        issue = random.choice(results)
        # print a link to the issue page on Comic Vine
        print(f"Random issue selected: ID: {issue['id']}")
        print(f"Find out more: {issue['site_detail_url']}")
        image_link = issue["image"]["original_url"]
        return image_link
    else:
        raise ValueError("No comic issues found for the specified series.")


def display_image_on_inky(image_url):
    # Display image on Inky Impression
    response = requests.get(image_url)
    response.raise_for_status()
    image = Image.open(BytesIO(response.content))
    response.close()

    # Rotate the image if it is taller than it is wide
    if image.height > image.width:
        image = image.rotate(90, expand=True)

    image = image.resize(inky_display.resolution)
    inky_display.set_image(image)
    print("Updating Inky Impression!")
    inky_display.show()


try:
    # Pick a random search term from the list
    search_query = random.choice(SEARCH_QUERIES)
    volume_id = find_volume_id(API_KEY, search_query)
    comic_image_url = fetch_random_comic_image(API_KEY, volume_id)
    display_image_on_inky(comic_image_url)
except Exception as e:
    print(f"Error: {e}")
```
