def normalize_alfa_profile(data: dict) -> dict:
    return {
        "username": data["username"],
        "total_solved": data["totalSolved"],
        "acceptance_rate": data.get("acceptanceRate", 0) / 100,
        "difficulty_split": {
            "easy": data["easySolved"],
            "medium": data["mediumSolved"],
            "hard": data["hardSolved"],
        },
    }
