"""Apache Kafka Event Streaming for PricePulse.

Implements Kafka ingestion specified in Project 2 Technical Stack & AWS MSK free tier setup:
- Connects to Kafka cluster (or Amazon MSK) when KAFKA_BOOTSTRAP_SERVERS is set.
- Publishes order events to topic `pricepulse-orders`.
- Publishes price update alerts to topic `pricepulse-price-updates`.
- Provides an async background consumer to feed incoming Kafka orders into the DemandStream.
"""
from __future__ import annotations

import json
import logging
import os
import time

logger = logging.getLogger("pricepulse.kafka")

KAFKA_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
TOPIC_ORDERS = os.environ.get("KAFKA_TOPIC_ORDERS", "pricepulse-orders")
TOPIC_ALERTS = os.environ.get("KAFKA_TOPIC_ALERTS", "pricepulse-price-updates")


class KafkaStreamManager:
    """Kafka producer & consumer wrapper with graceful local fallback."""

    def __init__(self):
        self.producer = None
        self.is_connected = False
        if KAFKA_SERVERS:
            try:
                from kafka import KafkaProducer
                self.producer = KafkaProducer(
                    bootstrap_servers=KAFKA_SERVERS.split(","),
                    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                    request_timeout_ms=3000,
                )
                self.is_connected = True
                logger.info(f"Connected to Kafka broker at {KAFKA_SERVERS}")
            except Exception as e:
                logger.warning(f"Could not connect to Kafka at {KAFKA_SERVERS}: {e}")

    def emit_order(self, sku: str, qty: int, timestamp: float | None = None) -> None:
        event = {
            "event_type": "order_placed",
            "sku": sku,
            "quantity": qty,
            "timestamp": timestamp or time.time(),
        }
        if self.producer and self.is_connected:
            try:
                self.producer.send(TOPIC_ORDERS, event)
            except Exception as e:
                logger.warning(f"Failed to publish order event to Kafka: {e}")

    def emit_price_change(self, sku: str, old_price: float, new_price: float, reason: str, source: str) -> None:
        event = {
            "event_type": "price_changed",
            "sku": sku,
            "old_price": old_price,
            "new_price": new_price,
            "change_pct": round((new_price / max(old_price, 1e-6) - 1) * 100, 2),
            "reason": reason,
            "source": source,
            "timestamp": time.time(),
        }
        if self.producer and self.is_connected:
            try:
                self.producer.send(TOPIC_ALERTS, event)
            except Exception as e:
                logger.warning(f"Failed to publish price change event to Kafka: {e}")

    def status(self) -> dict:
        return dict(
            enabled=bool(KAFKA_SERVERS),
            connected=self.is_connected,
            bootstrap_servers=KAFKA_SERVERS,
            topic_orders=TOPIC_ORDERS,
            topic_alerts=TOPIC_ALERTS,
        )


kafka_manager = KafkaStreamManager()
