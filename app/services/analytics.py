from typing import List, Dict
from app.utils.scoring import consistency_score


def analyze_topics(topic_stats: List[Dict]) -> Dict[str, List[str]]:
    """
    Identifies weak and strong topics based on accuracy thresholds.
    """
    weak_topics = []
    strong_topics = []

    for topic in topic_stats:
        accuracy = topic.get("accuracy", 0)

        if accuracy < 0.45:
            weak_topics.append(topic["topic"])
        elif accuracy > 0.65:
            strong_topics.append(topic["topic"])

    return {
        "weak_topics": weak_topics,
        "strong_topics": strong_topics
    }


def generate_signals(
    topic_stats: List[Dict],
    activity_dates: List[str]
) -> Dict:
    """
    Generates high-level performance signals.
    """
    topic_analysis = analyze_topics(topic_stats)

    return {
        **topic_analysis,
        "consistency_score": consistency_score(activity_dates)
    }
