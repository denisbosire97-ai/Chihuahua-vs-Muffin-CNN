# Denis Aosa Safetycoordinator Glasses
### Team Members: Denis Aosa

## Tier Selection
**Tier 2**
Justification: This project proposes a fully functional edge-deployed Computer Vision pipeline combining both object detection (bounding boxes) and pose estimation tracking. It moves beyond entry-level classification and tackles real-world computational logic constraints.

## Problem Statement
Delivery drivers handling 'Last 100 Yards' fulfillment face dangerous, unlit terrain such as broken stairs, unpredictable loose pets, and trip wires. These invisible hazards cause preventable injuries that directly cost logistics managers and drivers thousands in medical compensations and delayed shipments annually.

## Solution Overview
The **Denis Aosa Safetycoordinator Glasses** are a wearable prototype that acts as an automated safety buddy. An edge-mounted camera continuously evaluates the driver's POV, identifies critical obstacles natively, and monitors driver back-posture—triggering an instant visual HUD alert if a dangerous state is reached.

## Technical Approach
- **Technique**: Object Detection & Pose Detection
- **Model**: YOLOv8-Nano and MediaPipe
- **Framework**: PyTorch and Ultralytics YOLO ecosystem
- **Justification**: Wearable glasses require models that execute in under 30ms latency with minimal battery heat. YOLOv8-Nano achieves industry-leading FPS for objects, and MediaPipe maps posture without cloud processing.

## Dataset Plan
- **Source**: Public Kaggle/Roboflow datasets ("Residential Delivery Hazards") combined with manually curated images of porches.
- **Size**: Approximately 1,500 samples. 
- **Labels**: Bonding box annotations for `loose_pet`, `broken_stairs`, `low_obstacle`, `trip_wire` & skeleton nodes for knee/hip joints.

## Metrics
| Metric Type | Example | Target |
| :--- | :--- | :--- |
| Primary Metric | Recall for Critical Hazards | ≥ 95% (False negatives are dangerous) |
| Secondary Metric | Inference Speed | < 30ms per frame |

## Week-by-Week Plan
| Week | Task | Milestone |
| :--- | :--- | :--- |
| 10 (Oct 30) | Get dataset, format bounding boxes, set PyTorch | Dataset ready |
| 11 (Nov 6) | Train YOLOv8-Nano baseline | Model weights generated |
| 12 (Nov 13) | Establish HUD logic and posture angles | Logic pipeline working |
| 13 (Nov 20) | Test full system with sample driving videos | Good accuracy / Alerting |
| 14 (Nov 27) | Organize GitHub and write metrics documentation | Everything done |
| 15 (Dec 4) | Present Project to the class | 🎉 Presentation day |

## Resources Needed
| Resource | Options / Notes |
| :--- | :--- |
| Compute | Google Colab, Local TPU |
| Frameworks | PyTorch, Ultralytics, OpenCV |
| Estimated Cost | $0 (Open-source implementation) |

## Risks & Mitigation Table
| Risk | Probability | Mitigation |
| :--- | :--- | :--- |
| Pose estimation failing due to downward camera angle | High | Rely strictly on environmental bounding box hazards instead. |
| Inadequate dataset variance | Medium | Use algorithmic augmentations (rotation/brightness changes) via OpenCV. |

## AI Usage Log
- **AI Tool**: Antigravity Assistant (Gemini)
- **Application**: Assisted in generating the initial project scope proposal, structuring the GitHub repository mapping iteratively, and writing the Python logic scripts (`safety_logic.py`). Used for bounding-box methodology recommendations constraint validation.
