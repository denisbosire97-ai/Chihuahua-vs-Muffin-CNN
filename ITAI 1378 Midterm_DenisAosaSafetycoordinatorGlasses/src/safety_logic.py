import logging
from typing import Dict, Any, Tuple

# Set up simple logging for the Safety Agent
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def evaluate_safety_risk(environment_data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Evaluates the current environment for 'Last 100 Yards' hazards.
    Triggers a 'Stop & Assess' alert on the smart glasses HUD if high-risk is detected.

    Args:
        environment_data: dictionary containing detections and environmental state.
            Example:
            {
                "light_level": "low", # "low", "medium", "high"
                "hazards_detected": ["broken_stairs"], # List of bounding box labels
                "surface_condition": "wet", # "dry", "wet", "icy"
            }

    Returns:
        (alert_triggered, message): Boolean indicating if HUD alert should be shown, 
                                    and a reason message.
    """
    
    # 1. Critical Hazard Check (e.g. Broken stairs, loose dog, blocked path, forklifts)
    critical_hazards = ["broken_stairs", "loose_pet", "unsecured_ladder", "trip_wire", "forklift_proximity", "forklift_reversing"]
    detected_hazards = environment_data.get("hazards_detected", [])
    
    for hazard in detected_hazards:
        if hazard in critical_hazards:
            alert_msg = f"STOP & ASSESS: Critical hazard detected -> {str(hazard).replace('_', ' ').title()}."
            logging.warning(alert_msg)
            return True, alert_msg

    # 2. Environmental Condition Check (e.g. Unlit porch + icy ground)
    light_level = environment_data.get("light_level", "high")
    surface = environment_data.get("surface_condition", "dry")

    if light_level == "low" and surface in ["icy", "wet"]:
        alert_msg = f"STOP & ASSESS: High-risk environment -> Low visibility combined with {surface} surface."
        logging.warning(alert_msg)
        return True, alert_msg
    
    # 3. Low-hanging obstacle combined with low light
    if "low_obstacle" in detected_hazards and light_level == "low":
        alert_msg = "STOP & ASSESS: Low-visibility hazard -> Low-hanging obstacle detected."
        logging.warning(alert_msg)
        return True, alert_msg

    # Default: Safe
    return False, "Environment is safe."

# --- Example Usage for Testing ---
if __name__ == "__main__":
    test_scenario_1 = {
        "light_level": "low",
        "hazards_detected": [],
        "surface_condition": "icy"
    }
    alert, msg = evaluate_safety_risk(test_scenario_1)
    print(f"Scenario 1 - Alert: {alert} | Message: {msg}")

    test_scenario_2 = {
        "light_level": "high",
        "hazards_detected": ["loose_pet"],
        "surface_condition": "dry"
    }
    alert, msg = evaluate_safety_risk(test_scenario_2)
    print(f"Scenario 2 - Alert: {alert} | Message: {msg}")
