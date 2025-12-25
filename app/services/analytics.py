from typing import List, Dict


def compute_skill_topics(skill_data: Dict) -> List[Dict]:
    topics = []

    for level in ["fundamental", "intermediate", "advanced"]:
        for t in skill_data.get(level, []):
            topics.append({
                "name": t["tagName"],
                "solved": t["problemsSolved"],
                "level": level
            })

    return topics


def compute_signals(topics: List[Dict]) -> Dict:
    # sort by solved count
    sorted_topics = sorted(topics, key=lambda x: x["solved"], reverse=True)

    strong = [t["name"] for t in sorted_topics[:5]]
    weak = [t["name"] for t in sorted_topics[-5:]]

    return {
        "strong_topics": strong,
        "weak_topics": weak
    }
