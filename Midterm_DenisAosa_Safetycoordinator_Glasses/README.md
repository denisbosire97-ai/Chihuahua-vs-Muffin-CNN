# Denis Aosa Safetycoordinator Glasses - Midterm Project

## Overview
This repository contains the prototype components for the "Denis Aosa Safetycoordinator Glasses," a wearable computer vision system tailored for Amazon DSP drivers. The smart glasses act as a virtual safety coordinator for delivery drivers traversing the hazardous 'Last 100 Yards' to a customer's door.

## Capabilities
1. **Hazard Detection**: Highlights loose pets, broken stairs, missing lights, and trip wires using a lightweight `YOLOv8-Nano` model.
2. **Ergonomic Tracking**: Monitors driver posture via downward cameras utilizing pose-estimation to warn of poor lifting mechanics (bending at the waist).
3. **Safety Logic & Logging**: Automatically alerts drivers via HUD and uploads an incident report to the JSON schema for backend coordinators to review.

## Files
- `generate_pptx.py`: Generates the project slide deck.
- `AntiGravity_Safety_Agent/`: Contains the logic rules, schema, and design architectures.
