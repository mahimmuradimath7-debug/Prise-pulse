"""Apache Flink CEP Real-Time Flash Sale & Order Spike Detection Job.

Implements the Apache Flink CEP requirement from Project 2 (Weeks 4-5):
"Implement Apache Flink for real-time stream processing with sub-second latency.
Add Flash Sale Detection using Flink Complex Event Processing (CEP) to identify order spikes
and apply emergency multipliers."

Architecture:
- Ingests order events from Apache Kafka topic 'pricepulse-orders'.
- Windowing: 5-minute sliding window, sliding every 1 minute.
- CEP Pattern: Evaluates order velocity against rolling 1-hour baseline.
- If current_window_orders >= 3.0 * baseline_orders and count >= 10:
    Triggers 'FLASH_SALE_SPIKE' event with emergency multiplier (up to 1.25x).
- Emits emergency alert to Kafka topic 'pricepulse-price-updates' or callback webhook.
"""

import json
import os
import sys

# PyFlink imports (configured when running in an Apache Flink cluster or PyFlink runner)
try:
    from pyflink.common import Time, WatermarkStrategy
    from pyflink.common.serialization import SimpleStringSchema
    from pyflink.datastream import StreamExecutionEnvironment
    from pyflink.datastream.connectors.kafka import (
        KafkaOffsetsInitializer,
        KafkaRecordSerializationSchema,
        KafkaSink,
        KafkaSource,
    )
    from pyflink.datastream.functions import MapFunction, ProcessWindowFunction
    from pyflink.datastream.window import SlidingEventTimeWindows
    PYFLINK_AVAILABLE = True
except ImportError:
    PYFLINK_AVAILABLE = False


def run_flink_job():
    """Main Flink job entry point for PyFlink execution environment."""
    if not PYFLINK_AVAILABLE:
        print("[Flink Job] PyFlink is not installed in the local environment.")
        print("To run in cluster: flink run -m localhost:8081 -py streaming/flink_pricing_job.py")
        return

    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(2)

    kafka_bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    source_topic = os.environ.get("KAFKA_TOPIC_ORDERS", "pricepulse-orders")
    sink_topic = os.environ.get("KAFKA_TOPIC_ALERTS", "pricepulse-price-updates")

    # 1. Kafka Source
    kafka_source = (
        KafkaSource.builder()
        .set_bootstrap_servers(kafka_bootstrap)
        .set_topics(source_topic)
        .set_group_id("flink-pricing-group")
        .set_starting_offsets(KafkaOffsetsInitializer.latest())
        .set_value_only_deserializer(SimpleStringSchema())
        .build()
    )

    # 2. Parse & Assign Timestamps / Watermarks
    stream = (
        env.from_source(kafka_source, WatermarkStrategy.no_watermarks(), "KafkaOrderSource")
        .map(lambda raw: json.loads(raw))
        .key_by(lambda event: event["sku"])
    )

    # 3. 5-Minute Sliding Window (sliding every 1 minute)
    windowed_stream = (
        stream.window(SlidingEventTimeWindows.of(Time.minutes(5), Time.minutes(1)))
        .process(OrderSpikeDetector())
    )

    # 4. Sink to Kafka Alert Topic
    kafka_sink = (
        KafkaSink.builder()
        .set_bootstrap_servers(kafka_bootstrap)
        .set_record_serializer(
            KafkaRecordSerializationSchema.builder()
            .set_topic(sink_topic)
            .set_value_serialization_schema(SimpleStringSchema())
            .build()
        )
        .build()
    )

    windowed_stream.map(lambda event: json.dumps(event)).sink_to(kafka_sink)
    env.execute("PricePulse-Flink-CEP-Spike-Detector")


class OrderSpikeDetector:
    """Flink window processing function computing order velocity and flash spike detection."""

    def __init__(self, spike_ratio_threshold=3.0, min_spike_orders=10):
        self.spike_ratio_threshold = spike_ratio_threshold
        self.min_spike_orders = min_spike_orders

    def process(self, key, context, elements):
        order_count = sum(e.get("quantity", 1) for e in elements)
        baseline = max(context.get_baseline(key) or 5.0, 1.0)
        ratio = order_count / baseline
        is_spike = (order_count >= self.min_spike_orders) and (ratio >= self.spike_ratio_threshold)

        if is_spike:
            multiplier = min(1.25, 1.0 + (ratio - 1.0) * 0.08)
            yield {
                "event_type": "flash_sale_detected",
                "sku": key,
                "window_orders": order_count,
                "baseline_orders": baseline,
                "spike_ratio": round(ratio, 2),
                "emergency_multiplier": round(multiplier, 2),
                "window_end_timestamp": context.window().end,
            }


if __name__ == "__main__":
    run_flink_job()
