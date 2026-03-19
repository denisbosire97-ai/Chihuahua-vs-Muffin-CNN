# Anti-Gravity Safety Agent: System Design

## 1. Hazard Classification: The 'Last 100 Yards' Taxonomy

As delivery drivers approach the final 100 yards of the destination (e.g., walking from the van to the front porch), they encounter the highest density of unpredictable hazards. The CV model of the smart glasses must detect these 5 critical hazards:

| Hazard Name | Description | Risk Level |
| :--- | :--- | :--- |
| **Loose Pets / Dogs** | Unrestrained animals approaching the delivery point. | Critical |
| **Broken / Missing Stairs** | Damaged porch stairs, missing handrails, or gaps in decking. | Critical |
| **Uneven / Icy Pavement** | Potholes, sudden drops in the sidewalk, or frozen puddles. | Medium - Critical |
| **Low-Hanging Obstacles** | Tree branches or porch decorations at head-level. | Medium |
| **Trip Wires / Debris** | Garden hoses, extension cords, or scattered toys blocking the walking path. | Medium |

### Proposed CV Model Architecture
**Recommendation:** **YOLOv8-Nano (You Only Look Once, v8 Nano version)**
- **Why YOLOv8-Nano?** Smart glasses (edge devices) have severe battery and compute constraints. YOLOv8-Nano is small enough (under 4MB weights) to run at >30 FPS on edge processors (like Snapdragon XR2 or Google Coral Edge TPU), ensuring real-time `Stop & Assess` alerts without catastrophic battery drain.
- **Capabilities:** It excels at bounding box (Object Detection) in diverse lighting and can be easily fine-tuned via PyTorch for edge formats like ONNX or TFLite.

---

## 2. Ergonomic Monitoring: Real-time Posture Feedback

Drivers repeatedly picking up heavy packages are at high risk for musculoskeletal injuries. The glasses can leverage the downward-facing or field-of-view camera to monitor body mechanics.

### Methodology: Pose Estimation
We will deploy **YOLOv8-Pose** or Google's **MediaPipe Pose** to track skeletal landmarks. 

1. **Detection Phase:** Wait for the driver to approach the van shelf or ground package (indicated by looking down at a box and leaning forward).
2. **Keypoint Tracking:** The model tracks the angle between three primary keypoints:
   - Shoulders
   - Hips (or lower torso estimation if partially occluded)
   - Knees
3. **Logic Threshold:** If the angle of the driver's spine drops below 45 degrees relative to the ground while the knees remain mostly straight (an angle > 160 degrees), it indicates a "bending at the waist" motion rather than "lifting with the legs."
4. **HUD Cues:**
   - **Green Checkmark / Border**: Driver's knees are bent, back is straight.
   - **Flashing Orange Warning**: Driver's back is excessively arched or lifting entirely at the waist. "STRAIGHTEN BACK, BEND KNEES" text overlay appears instantly on the glasses HUD.
