# Denis Aosa Safetycoordinator Glasses
### Team Members: Denis Aosa

## Tier Selection
**Tier 2**
Justification: This project proposes a fully functional edge-deployed Computer Vision pipeline combining both object detection (bounding boxes) and pose estimation tracking. It moves beyond entry-level classification and tackles real-world computational logic constraints for logistics workers.

## Problem Statement
Logistics workers spanning both warehouse floors and external delivery routes face constant hazards. Delivery drivers endure dangerous 'Last 100 Yards' conditions (broken stairs, loose pets), while warehouse workers risk catastrophic forklift collisions and improper lifting injuries. These incidents directly cost companies millions in medical compensations and lost productivity.

## Solution Overview
The **Denis Aosa Safetycoordinator Glasses** are a wearable prototype that acts as an automated safety buddy for all logistics staff. An edge-mounted camera continuously evaluates the worker's POV, identifies critical obstacles natively (forklifts, stairs), and monitors back-posture—triggering an instant visual HUD alert if a dangerous state is reached.

## Technical Approach
- **Technique**: Object Detection & Pose Detection
- **Model**: YOLOv8-Nano and MediaPipe
- **Framework**: PyTorch and Ultralytics YOLO ecosystem
- **Justification**: Wearable glasses require models that execute in under 30ms latency with minimal battery heat. YOLOv8-Nano achieves industry-leading FPS for objects, and MediaPipe maps posture without cloud processing.

## Dataset Plan
- **Source**: Public Kaggle/Roboflow datasets ("Warehouse Safety" and "Residential Delivery Hazards").
- **Size**: Approximately 2,000 samples. 
- **Labels**: Bonding box annotations for `forklift`, `loose_pet`, `broken_stairs`, `low_obstacle` & skeleton nodes for knee/hip joints.

## Metrics
| Metric Type | Example | Target |
| :--- | :--- | :--- |
| Primary Metric | Recall for Critical Hazards | ≥ 95% (Missing a forklift alert is disastrous) |
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
| Inadequate dataset variance for forklift crashes | Medium | Use algorithmic augmentations or synthetic renders via Carla simulator. |

## AI Usage Log
- **AI Tool**: Antigravity Assistant (Gemini)
- **Application**: Assisted in generalizing the project logic to cover both delivery routing and warehouse forklift safety. Structured the GitHub repository mapping iteratively, configured the PPTX generator, and authored the Python logic scripts (`safety_logic.py`).
