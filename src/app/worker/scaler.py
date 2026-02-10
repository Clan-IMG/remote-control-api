"""
Container Scaler - Manages auto-scaling of worker containers.
Monitors queue depth and container load to scale up/down.
"""

import asyncio
import logging
import docker
from typing import Optional
from collections import deque
import time

from src.app.config import (
    MIN_CONTAINERS, MAX_CONTAINERS, 
    SCALING_THRESHOLD, MAXIMUM_REQUESTS
)
from src.app.redis_client import (
    get_redis, QUEUE_PENDING, KEY_CONTAINER_STATUS, KEY_CONTAINER_LOAD
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ContainerScaler:
    def __init__(self):
        self.docker_client = docker.from_env()
        self.worker_image = "pixelkid-worker:latest"
        self.network_name = "pixelkid-network"
        # queue history for growth projection: deque of (timestamp, depth)
        self.queue_history: deque[tuple[float, int]] = deque(maxlen=10)
    
    async def get_queue_depth(self) -> int:
        """Get number of pending requests"""
        redis = await get_redis()
        return await redis.llen(QUEUE_PENDING)
    
    async def get_container_loads(self) -> dict[str, int]:
        """Get load percentage for each container"""
        redis = await get_redis()
        loads = await redis.hgetall(KEY_CONTAINER_LOAD)
        return {k: int(v) for k, v in loads.items()}
    
    async def get_running_containers(self) -> list[str]:
        """Get list of running worker container IDs"""
        redis = await get_redis()
        statuses = await redis.hgetall(KEY_CONTAINER_STATUS)
        return [k for k, v in statuses.items() if v == "running"]
    
    def start_worker_container(self) -> Optional[str]:
        """Start a new worker container"""
        try:
            container = self.docker_client.containers.run(
                self.worker_image,
                detach=True,
                network=self.network_name,
                environment={
                    "REDIS_HOST": "redis",
                    "DATABASE_URL": "${DATABASE_URL}",
                },
                labels={"pixelkid.type": "worker"},
                auto_remove=True
            )
            logger.info(f"Started new worker container: {container.id[:12]}")
            return container.id
        except Exception as e:
            logger.error(f"Failed to start worker container: {e}")
            return None
    
    def stop_worker_container(self, container_id: str) -> bool:
        """Stop a worker container"""
        try:
            container = self.docker_client.containers.get(container_id)
            container.stop(timeout=30)
            logger.info(f"Stopped worker container: {container_id[:12]}")
            return True
        except Exception as e:
            logger.error(f"Failed to stop container {container_id}: {e}")
            return False
    
    async def evaluate_scaling(self):
        """Evaluate if we need to scale up or down"""
        running = await self.get_running_containers()
        current_count = len(running)
        queue_depth = await self.get_queue_depth()
        loads = await self.get_container_loads()
        now = time.time()
        # record history for projection
        self.queue_history.append((now, queue_depth))
        
        # Calculate average load
        avg_load = sum(loads.values()) / len(loads) if loads else 0
        
        logger.info(
            f"Scaling check: {current_count} containers, "
            f"{queue_depth} queued, {avg_load:.1f}% avg load"
        )
        
        # Scale up conditions
        # Proactive scale-up using projected queue growth
        from src.app.config import SCALING_LOOKAHEAD_SECONDS, SCALING_PROJECTED_UTILIZATION

        projected_queue = queue_depth
        # Use linear growth estimate if we have at least two samples
        if len(self.queue_history) >= 2:
            t0, q0 = self.queue_history[0]
            t1, q1 = self.queue_history[-1]
            dt = max(1.0, t1 - t0)
            growth_per_sec = (q1 - q0) / dt
            projected_queue = max(0, int(queue_depth + growth_per_sec * SCALING_LOOKAHEAD_SECONDS))

        total_capacity = max(1, current_count * MAXIMUM_REQUESTS)

        should_scale_up = (
            current_count < MAX_CONTAINERS and
            (
                avg_load >= SCALING_THRESHOLD or
                projected_queue > total_capacity * SCALING_PROJECTED_UTILIZATION
            )
        )
        
        # Scale down conditions  
        should_scale_down = (
            current_count > MIN_CONTAINERS and
            avg_load < 30 and
            queue_depth < current_count * MAXIMUM_REQUESTS * 0.1
        )
        
        if should_scale_up:
            # Calculate how many workers to add to cover projected_queue
            needed = 0
            if projected_queue > total_capacity:
                deficit = projected_queue - total_capacity
                needed = (deficit + MAXIMUM_REQUESTS - 1) // MAXIMUM_REQUESTS

            # Ensure we don't exceed MAX_CONTAINERS
            to_start = min(needed if needed > 0 else 1, MAX_CONTAINERS - current_count)
            logger.info(f"Scaling up: starting {to_start} worker(s) (projected_queue={projected_queue}, capacity={total_capacity})")
            for _ in range(to_start):
                self.start_worker_container()
            
        elif should_scale_down:
            # Find container with lowest load
            if loads:
                lowest = min(loads.items(), key=lambda x: x[1])
                logger.info(f"Scaling down: stopping {lowest[0]}")
                self.stop_worker_container(lowest[0])
    
    async def run_scaler_loop(self, interval: int = 30):
        """Main loop - check scaling every interval seconds"""
        logger.info("Container scaler started")
        
        # Ensure minimum containers are running
        running = await self.get_running_containers()
        while len(running) < MIN_CONTAINERS:
            self.start_worker_container()
            await asyncio.sleep(2)
            running = await self.get_running_containers()
        
        while True:
            try:
                await self.evaluate_scaling()
            except Exception as e:
                logger.error(f"Scaling error: {e}")
            
            await asyncio.sleep(interval)


async def main():
    scaler = ContainerScaler()
    await scaler.run_scaler_loop()


if __name__ == "__main__":
    asyncio.run(main())
