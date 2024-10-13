import math
import time
import json

import requests


# constants


SERVER_URL = "games-test.datsteam.dev"
HEADERS = {"X-Auth-Token": "6707d9ae72b1e6707d9ae72b21"}
state = {}


# utils


def _calculate_distance_between_coords(coord_from: dict, coord_to: dict) -> float:
    return math.sqrt(
        (coord_to["x"] - coord_from["x"]) ** 2 + (coord_to["y"] - coord_from["y"]) ** 2
    )


def _vector_length(vector: dict) -> float:
    return math.sqrt(vector["x"] ** 2 + vector["y"] ** 2)


def _normalize_vector(vector: dict, max_length) -> dict:
    # Calculate the current length (magnitude) of the vector
    scale = max_length / _vector_length(vector)
    return {
        "x": vector["x"] * scale,
        "y": vector["y"] * scale,
    }


def _is_coord_in_triangle(
    triangle_coord_1: dict,
    triangle_coord_2: dict,
    triangle_coord_3: dict,
    target_coord: dict,
) -> bool:
    def area(p1: dict, p2: dict, p3: dict) -> float:
        return abs(
            (
                p1["x"] * (p2["y"] - p3["y"])
                + p2["x"] * (p3["y"] - p1["y"])
                + p3["x"] * (p1["y"] - p2["y"])
            )
            / 2.0
        )

    total_area = area(triangle_coord_1, triangle_coord_2, triangle_coord_3)

    area1 = area(target_coord, triangle_coord_2, triangle_coord_3)
    area2 = area(triangle_coord_1, target_coord, triangle_coord_3)
    area3 = area(triangle_coord_1, triangle_coord_2, target_coord)

    return total_area == area1 + area2 + area3


def _rotate_vector(vector: dict, angle_degrees: float) -> dict:
    angle_radians = math.radians(angle_degrees)

    return {
        "x": (
            vector["x"] * math.cos(angle_radians)
            - vector["y"] * math.sin(angle_radians)
        ),
        "y": (
            vector["x"] * math.sin(angle_radians)
            + vector["y"] * math.cos(angle_radians)
        ),
    }


def _is_coin_on_path(transport: dict, coin_coord: dict) -> bool:
    direction_to_coin = {
        "x": coin_coord["x"] - transport["x"],
        "y": coin_coord["y"] - transport["y"],
    }

    length_velocity = _vector_length(transport["velocity"])
    length_to_coin = _vector_length(direction_to_coin)

    normalized_velocity = _normalize_vector(transport["velocity"], length_velocity)

    dot_product = (
        normalized_velocity["x"] * direction_to_coin["x"]
        + normalized_velocity["y"] * direction_to_coin["y"]
    )

    return dot_product > 0 and length_to_coin > 0


def _calculate_acceleration_to_reach_target(
    transport: dict, target_coord: dict, max_acceleration: float
) -> dict:
    direction_to_target = {
        "x": target_coord["x"] - transport["x"],
        "y": target_coord["y"] - transport["y"],
    }

    required_velocity = _normalize_vector(
        direction_to_target, _vector_length(transport["velocity"])
    )

    velocity_difference = {
        "x": required_velocity["x"] - transport["velocity"]["x"],
        "y": required_velocity["y"] - transport["velocity"]["y"],
    }

    if velocity_difference == 0:
        return _normalize_vector(direction_to_target, max_acceleration)
    if _is_coin_on_path(transport, target_coord):
        return _normalize_vector(direction_to_target, max_acceleration)
    else:
        return _normalize_vector(velocity_difference, max_acceleration)


def _get_richest_bounty_in_view(
    transport: dict,
    triangle_coord_2: dict,
    triangle_coord_3: dict,
    bounties: list[dict],
) -> dict | None:
    for o in sorted(bounties, key=lambda x: -x["points"]):
        if _is_coord_in_triangle(transport, triangle_coord_2, triangle_coord_3, o):
            return o


# game logic


def main_loop() -> None:
    global state

    max_speed_over_max_accel = state["maxSpeed"] / state["maxAccel"]
    while True:
        # current state for debug
        print(f"{state['points']=}")
        if state["errors"]:
            print(f"{state['errors']=}")

        # build request_body
        request_body = {"transports": []}
        bounties = state["bounties"]
        enemies = state["enemies"]
        for t in state["transports"]:
            if t["status"] == "dead":
                print(f"    [{t['id']}]     lost carpet! {t['health']=}")
                if (
                    t["x"] <= 0
                    or t["x"] >= state["mapSize"]["x"]
                    or t["y"] <= 0
                    or t["y"] >= state["mapSize"]["y"]
                ):
                    print(f"    [{t['id']}]     in the end of the map")
                    print(f"    [{t['id']}]     {t['selfAcceleration']=}")
                    print(f"    [{t['id']}]     {t['anomalyAcceleration']=}")
                    print(f"    [{t['id']}]     {t['x']=}, {t['y']=}")
                    continue
            this_transport_request = {"id": t["id"]}

            # calculate cone of view
            if _vector_length(t["velocity"]) <= 1:
                t["velocity"] = {
                    "x": -min(t["x"] - 0, state["mapSize"]["x"] - t["x"]),
                    "y": -min(t["y"] - 0, state["mapSize"]["y"] - t["y"]),
                }
            view_center = _normalize_vector(t["velocity"], state["maxAccel"])
            cone_of_view_angle = 60
            left_side = _rotate_vector(view_center, cone_of_view_angle)
            right_side = _rotate_vector(view_center, -cone_of_view_angle)

            # move around anomalies
            for anomaly in state["anomalies"]:
                distance = _calculate_distance_between_coords(
                    {
                        "x": t["x"] + t["velocity"]["x"] * 2,
                        "y": t["y"] + t["velocity"]["y"] * 2,
                    },
                    {
                        "x": anomaly["x"] + anomaly["velocity"]["x"] * 2,
                        "y": anomaly["y"] + anomaly["velocity"]["y"] * 2,
                    },
                )

                if distance < anomaly["radius"]:
                    view_center = _rotate_vector(view_center, cone_of_view_angle)
                    left_side = _rotate_vector(left_side, cone_of_view_angle)
                    right_side = _rotate_vector(right_side, cone_of_view_angle)
                    print(f"    [{t['id']}] avoiding anomaly")
                    acceleration_target = "anomaly free zone"

            # get bounty
            closest_bounty = _get_richest_bounty_in_view(
                transport=t,
                triangle_coord_2={
                    "x": left_side["x"] + t["x"],
                    "y": left_side["y"] + t["y"],
                },
                triangle_coord_3={
                    "x": right_side["x"] + t["x"],
                    "y": right_side["y"] + t["y"],
                },
                bounties=bounties,
            )

            acceleration_target_coord, acceleration_target = (
                (
                    {
                        "x": closest_bounty["x"],
                        "y": closest_bounty["y"],
                    },
                    "bounty",
                )
                if closest_bounty
                else (view_center, "somewhere")
            )

            # get acceleration and clip it if it's more than `maxAccel`
            acceleration = _calculate_acceleration_to_reach_target(
                t,
                acceleration_target_coord,
                state["maxAccel"],
            )
            if _vector_length(acceleration) > 10:
                acceleration["x"] *= 0.99
                acceleration["y"] *= 0.99

            # if near end of the map then change direction
            t_future_position = {
                "x": t["x"] + t["velocity"]["x"] * max_speed_over_max_accel,
                "y": t["y"] + t["velocity"]["y"] * max_speed_over_max_accel,
            }
            if (
                t_future_position["x"] <= 0
                or t_future_position["x"] >= state["mapSize"]["x"]
            ):
                acceleration["x"] = min(t["x"] - 0, state["mapSize"]["x"] - t["x"])
                acceleration_target = "game world"
            if (
                t_future_position["y"] <= 0
                or t_future_position["y"] >= state["mapSize"]["y"]
            ):
                acceleration["y"] = min(t["y"] - 0, state["mapSize"]["y"] - t["y"])
                acceleration_target = "game world"

            this_transport_request["acceleration"] = acceleration

            # kill reachest guy in the way
            if t["attackCooldownMs"] == 0:
                richest_enemies = sorted(enemies, key=lambda e: -e["killBounty"])
                for e in richest_enemies:
                    e_next_position = {
                        "x": int(e["x"] + e["velocity"]["x"]),
                        "y": int(e["y"] + e["velocity"]["y"]),
                    }
                    if (
                        (
                            _calculate_distance_between_coords(
                                {
                                    "x": t["x"]
                                    + this_transport_request["acceleration"]["x"],
                                    "y": t["y"]
                                    + this_transport_request["acceleration"]["y"],
                                },
                                e_next_position,
                            )
                            <= state["attackRange"]
                        )  # TODO: sometimes yields `attack distance is too far away: 226.83, max allowed 200.00`
                        and e["shieldLeftMs"] == 0
                    ):
                        this_transport_request["attack"] = e_next_position
                        if t["shieldCooldownMs"] == 0:
                            this_transport_request["activateShield"] = True
                        print(
                            f"    [{t['id']}] attacking bounty {e['killBounty']}! carpet health {t['health']}"
                        )
                        break

            print(f"    [{t['id']}] {acceleration_target=}")
            if acceleration_target == "game world":
                print(
                    f"    [{t['id']}] {acceleration=} {_vector_length(t['velocity'])=}"
                )
            request_body["transports"].append(this_transport_request)

        # senging info, updating state and waiting for API limit to slow down
        resp = requests.post(
            f"https://{SERVER_URL}/play/magcarp/player/move",
            headers=HEADERS,
            json=request_body,
        )
        if resp.status_code != 200:
            raise ValueError(
                f"panic with code: {resp.status_code}, body: {resp.json()}"
            )
        state = resp.json()
        with open("state.json", "w", encoding="UTF-8") as f:
            json.dump(state, f)
        time.sleep(0.33)


if __name__ == "__main__":
    resp = requests.post(
        f"https://{SERVER_URL}/play/magcarp/player/move", headers=HEADERS
    )
    if resp.status_code != 200:
        raise ValueError(f"panic with code: {resp.status_code}, body: {resp.json()}")
    state = resp.json()
    main_loop()
