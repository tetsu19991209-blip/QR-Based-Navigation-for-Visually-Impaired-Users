# QR-Based Indoor Navigation for Visually Impaired Users

A Python-based indoor navigation prototype designed to assist people with visual impairments in navigating indoor environments. The system identifies the user's current location through QR codes, calculates an indoor route using the A* pathfinding algorithm, and provides visual and voice-guided navigation instructions.

## Project Overview

Navigating unfamiliar indoor environments can be challenging for people with visual impairments because GPS signals are often unavailable or inaccurate inside buildings.

This project uses QR codes installed at known indoor locations to determine the user's current position. After scanning a QR code, the user can select or speak a destination. The system then calculates a route across the building map and provides step-by-step voice instructions.

## Key Features

- QR-based indoor position identification
- Real-time QR scanning through a webcam
- Colored QR code detection
- A* indoor pathfinding
- Multi-floor route calculation
- Floor-aware heuristic and stair-transition costs
- Text and voice destination input
- Text-to-speech navigation guidance
- Estimated walking steps between locations
- Interactive indoor map with route visualization
- Current-position and destination indicators
- Zooming, panning, and floor switching
- JSON-based storage for nodes, coordinates, and connections
- QR code generation for supported indoor locations
- Optional hybrid QR detection using OpenCV and YOLO

## How the System Works

1. The user opens the application.
2. The webcam scans a QR code placed at an indoor location.
3. The QR payload identifies the current node, coordinates, neighbouring nodes, and floor.
4. The current position is saved in `current_position.json`.
5. The user enters or speaks a destination.
6. The system loads the indoor graph from `nodes_map.json`.
7. The A* algorithm calculates a route from the current node to the destination.
8. The calculated route is displayed on the indoor map.
9. Step-by-step directions are shown and read aloud using text-to-speech.

## A* Pathfinding

The indoor navigation route is calculated using the A* search algorithm.

Each location is represented as a node, while connections between locations are represented as graph edges. 
The implementation uses Euclidean distance to estimate the cost of travelling between two nodes:


distance = √((x₂ - x₁)² + (y₂ - y₁)²)

The priority of each candidate node is calculated using:
f(n) = g(n) + h(n)

Where:

g(n) is the accumulated travel cost from the starting node.
h(n) is the estimated distance from the current node to the destination.
A floor difference cost is included in the heuristic.
An additional penalty is applied when transitioning between stairs on different floors.

The calculated pixel distance may also be converted into an estimated number of walking steps.

## QR Positioning

Each generated QR code contains location information such as:

{
  "Node": "N001",
  "Coordinate": {
    "x": 120,
    "y": 250
  },
  "Neigbours": ["N002", "N003"],
  "Action": "Current Position",
  "meta": {
    "type": "lab_classroom",
    "floor": 1,
    "color": "blue"
  }
}

After a successful scan, the decoded information is written to current_position.json. The navigation interface monitors this file and updates the current position when a new QR code is scanned.

The scanner also provides camera-positioning guidance, such as moving closer, centring the QR code, adjusting the camera direction, or holding the camera steady.

## Voice Guidance

The system supports accessibility-focused voice interaction through:

pyttsx3 for offline text-to-speech output
SpeechRecognition for destination input
Spoken turn-by-turn route instructions
Estimated walking-step instructions
Voice announcements for stairs and destination arrival
Special destination recognition for locations such as toilets, ATM facilities, and food areas
Interactive Map

The route guide is implemented with Tkinter and Pillow. It supports:

Ground-floor and first-floor maps
Route-line rendering
Current-location highlighting
Destination highlighting
Node and graph-edge visualization
Mouse-wheel zooming
Click-and-drag map panning
Manual floor switching
Automatic floor selection after QR scanning

## Technologies Used
| Technology         | Purpose                                              |
| ------------------ | ---------------------------------------------------- |
| Python             | Main programming language                            |
| Tkinter            | Desktop graphical user interface                     |
| OpenCV             | Webcam access and QR detection                       |
| NumPy              | Image and coordinate calculations                    |
| Pillow             | Map and interface image processing                   |
| A* Search          | Indoor route calculation                             |
| heapq            | Priority queue for A* search                         |
| JSON               | Storage of nodes, coordinates, and application state |
| pyttsx3            | Text-to-speech navigation                            |
| SpeechRecognition  | Voice destination input                              |
| PyAudio            | Microphone access                                    |
| qrcode             | Colored QR code generation                           |
| YOLO / Ultralytics | Optional QR-region detection fallback                |
| Threading          | Non-blocking speech and scanning operations          |

## Project Structure
QR-Based-Navigation-for-Visually-Impaired-Users/
├── main.py
├── routeGuide.py
├── qrReader.py
├── qrDetect.py
├── qrGenerate.py
├── nodes_map.json
├── current_position.json
├── requirements.txt
├── map/
│   ├── ground_floor.png
│   ├── first_floor.png
│   └── map_editor.html
├── project_images/
│   ├── Homepage_background.jpeg
│   └── qr_codes_colored/
└── qr_codes_colored/

## Main Files
main.py — Main application interface and program launcher.
qrReader.py — Reads QR codes through the webcam and updates the current position.
routeGuide.py — Calculates routes, renders maps, and generates navigation instructions.
qrGenerate.py — Generates colored QR codes from node data.
qrDetect.py — Experimental hybrid QR detection using image enhancement, OpenCV, contour detection, and YOLO.
nodes_map.json — Stores indoor nodes, coordinates, floors, neighbours, and navigation actions.
current_position.json — Stores the most recently scanned position.
Installation

**1. Clone the repository**
git clone https://github.com/tetsu19991209-blip/QR-Based-Navigation-for-Visually-Impaired-Users.git
cd QR-Based-Navigation-for-Visually-Impaired-Users

**2. Create a virtual environment**
python -m venv .venv
Activate it on Windows:
.venv\Scripts\activate

**3. Install the dependencies**
pip install -r requirements.txt
PyAudio installation may depend on the operating system and Python version.
The current prototype is primarily designed for Windows because it uses pywin32 for speech-related functionality.

**Running the Application**
Start the main application:
python main.py

**From the main interface:**
Select Scan and Read QR code.
Position the QR code in front of the webcam.
Allow the scanner to identify the current location.
Enter or speak a destination.
Follow the displayed and spoken navigation instructions.

**To open the route guide directly:**
python routeGuide.py

**To generate QR codes from nodes_map.json:**
python qrGenerate.py

## Team Members

This project was developed for the UCCC2513 Mini Project by P9 Group 3 in June 2025 Semester.

| Team Member    | Student ID |
| -------------- | ---------- |
| Chan Yi Hen    | 2305700    |
| Chong Zhi Cong | 2300083    |
| Shak Yong Sim  | 2400233    |
| Yap Ern Ru     | 2400070    |

## Acknowledgements

Developed as an academic mini project to explore QR positioning, computer vision, accessible interface design,
voice interaction, and graph-based indoor navigation.
