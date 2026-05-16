"""
Decision Scoring Engine for the Cloud Simulator.
Implements mathematically bounded, deterministic metric normalization and grading.
"""

from typing import Dict, Any, Tuple


class MetricNormalizer:
    """Normalizes raw simulation metrics into bounded 0-100 scores."""

    @staticmethod
    def normalize_latency(p95_latency: float, target_latency: float, rps: float) -> float:
        """
        Normalize latency.
        - If rps == 0 (no load), score is 100.
        - If p95 <= target, score is 100.
        - Penalty scales logarithmically/linearly above target.
        """
        if rps <= 0:
            return 100.0
            
        if target_latency <= 0:
            target_latency = 1.0  # Prevent division by zero
            
        if p95_latency <= target_latency:
            return 100.0
            
        penalty = ((p95_latency - target_latency) / target_latency) * 50.0
        return max(0.0, 100.0 - penalty)

    @staticmethod
    def normalize_cost(actual_cost: float, budget: float) -> float:
        """
        Normalize cost against a budget constraint.
        - If budget is <= 0:
            - If actual_cost == 0, score is 100 (perfect).
            - If actual_cost > 0, score is 0 (unauthorized spend).
        - Cost <= budget -> 100
        - Overspending applies a linear penalty. 2x budget = 0 score.
        """
        if budget <= 0:
            return 100.0 if actual_cost == 0 else 0.0
            
        if actual_cost == 0:
            return 100.0
            
        if actual_cost <= budget:
            return 100.0
            
        penalty = ((actual_cost - budget) / budget) * 100.0
        return max(0.0, 100.0 - penalty)

    @staticmethod
    def normalize_efficiency(cpu_avg: float, capacity: float, rps: float) -> float:
        """
        Normalize efficiency based on an optimal target band (e.g., 70% CPU).
        - If capacity is 0 and load exists, CPU defaults to 100% (overload).
        - If capacity is 0 and no load exists, score is 100% (perfectly idle).
        - If capacity > 0 and no load exists, score is 0% (wasted resources).
        """
        target_mid = 70.0
        
        if capacity <= 0:
            if rps > 0:
                # Overload / No capacity for load
                cpu_val = 100.0
            else:
                # Perfectly idle - no resources, no load.
                return 100.0
        else:
            cpu_val = max(0.0, min(100.0, cpu_avg))
            
        distance = abs(cpu_val - target_mid)
        # 1.5x penalty per point away from 70%.
        # E.g., CPU=100 -> dist=30 -> score=55. CPU=0 -> dist=70 -> score=0 (wasted resources).
        score = 100.0 - (distance * 1.5)
        return max(0.0, score)

    @staticmethod
    def normalize_reliability(dropped_requests: int, queue_ms: float) -> float:
        """
        Normalize reliability.
        - Strict boolean check: dropped_requests > 0 -> 0 score.
        - Heavy queue warning -> 50 score.
        - Otherwise -> 100.
        """
        if dropped_requests > 0:
            return 0.0
            
        if queue_ms > 1000.0:
            return 50.0
            
        return 100.0


class DecisionScorer:
    """Aggregates normalized metrics into a final graded evaluation."""

    @staticmethod
    def get_grade(score: float, dropped_requests: int = 0) -> str:
        """Map a 0-100 score to a letter grade with strict failure constraints."""
        if dropped_requests > 0:
            if score >= 60.0:
                return "D"
            return "F"
            
        if score >= 90.0:
            return "A"
        elif score >= 80.0:
            return "B"
        elif score >= 70.0:
            return "C"
        elif score >= 60.0:
            return "D"
        else:
            return "F"

    @classmethod
    def calculate_score(
        cls, 
        raw_metrics: Dict[str, float], 
        weights: Dict[str, float], 
        constraints: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Calculate the final weighted score from raw metrics and scenario weights.
        
        raw_metrics should contain:
          - p95_latency
          - rps
          - actual_cost
          - cpu_avg
          - capacity
          - dropped_requests
          - queue_ms
          
        weights should contain:
          - wL (latency weight)
          - wC (cost weight)
          - wE (efficiency weight)
          - wR (reliability weight)
          
        constraints should contain:
          - target_latency
          - budget
        """
        dropped_requests = int(raw_metrics.get("dropped_requests", 0))
        
        # 1. Normalize all metrics
        score_L = MetricNormalizer.normalize_latency(
            p95_latency=raw_metrics.get("p95_latency", 0.0),
            target_latency=constraints.get("target_latency", 100.0),
            rps=raw_metrics.get("rps", 0.0)
        )
        
        score_C = MetricNormalizer.normalize_cost(
            actual_cost=raw_metrics.get("actual_cost", 0.0),
            budget=constraints.get("budget", 0.0)
        )
        
        score_E = MetricNormalizer.normalize_efficiency(
            cpu_avg=raw_metrics.get("cpu_avg", 0.0),
            capacity=raw_metrics.get("capacity", 1.0),
            rps=raw_metrics.get("rps", 0.0)
        )
        
        score_R = MetricNormalizer.normalize_reliability(
            dropped_requests=dropped_requests,
            queue_ms=raw_metrics.get("queue_ms", 0.0)
        )
        
        # 2. Extract weights
        w_L = weights.get("wL", 0.25)
        w_C = weights.get("wC", 0.25)
        w_E = weights.get("wE", 0.25)
        w_R = weights.get("wR", 0.25)
        
        # Ensure weights sum to 1.0 roughly, fallback gracefully if not
        total_weight = w_L + w_C + w_E + w_R
        if total_weight > 0:
            w_L /= total_weight
            w_C /= total_weight
            w_E /= total_weight
            w_R /= total_weight
            
        # 3. Aggregate Final Score
        final_score = (w_L * score_L) + (w_C * score_C) + (w_E * score_E) + (w_R * score_R)
        
        # 4. Apply harsh penalty if there's downtime (dropped requests)
        if dropped_requests > 0:
            final_score *= 0.4
            
        final_score = round(final_score, 1)
        
        return {
            "score": final_score,
            "grade": cls.get_grade(final_score, dropped_requests),
            "breakdown": {
                "latency": round(score_L, 1),
                "cost": round(score_C, 1),
                "efficiency": round(score_E, 1),
                "reliability": round(score_R, 1)
            }
        }
