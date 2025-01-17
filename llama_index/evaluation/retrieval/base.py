"""Base retrieval abstractions."""

import asyncio
from abc import abstractmethod
from typing import Any, List, Dict
from llama_index.bridge.pydantic import BaseModel, Field
from llama_index.evaluation.retrieval.metrics_base import (
    BaseRetrievalMetric,
    RetrievalMetricResult,
)
from llama_index.evaluation.retrieval.metrics import resolve_metrics
from llama_index.finetuning.embeddings.common import EmbeddingQAFinetuneDataset


class RetrievalEvalResult(BaseModel):
    """Retrieval eval result.

    NOTE: this abstraction might change in the future.

    Attributes:
        query (str): Query string
        expected_ids (List[str]): Expected ids
        retrieved_ids (List[str]): Retrieved ids
        metric_dict (Dict[str, BaseRetrievalMetric]): \
            Metric dictionary for the evaluation

    """

    class Config:
        arbitrary_types_allowed = True

    query: str = Field(..., description="Query string")
    expected_ids: List[str] = Field(..., description="Expected ids")
    retrieved_ids: List[str] = Field(..., description="Retrieved ids")

    metric_dict: Dict[str, RetrievalMetricResult] = Field(
        ..., description="Metric dictionary for the evaluation"
    )

    @property
    def metric_vals_dict(self) -> Dict[str, float]:
        """Dictionary of metric values."""
        return {k: v.score for k, v in self.metric_dict.items()}

    def __str__(self) -> str:
        """String representation."""
        return f"Query: {self.query}\n" f"Metrics: {str(self.metric_vals_dict)}\n"


class BaseRetrievalEvaluator(BaseModel):
    """Base Retrieval Evaluator class."""

    metrics: List[BaseRetrievalMetric] = Field(
        ..., description="List of metrics to evaluate"
    )

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def from_metric_names(
        cls, metric_names: List[str], **kwargs: Any
    ) -> "BaseRetrievalEvaluator":
        """Create evaluator from metric names.

        Args:
            metric_names (List[str]): List of metric names
            **kwargs: Additional arguments for the evaluator

        """
        metrics = resolve_metrics(metric_names)
        return cls(metrics=metrics, **kwargs)

    @abstractmethod
    async def _aget_retrieved_ids(self, query: str) -> List[str]:
        """Get retrieved ids."""
        raise NotImplementedError

    def evaluate(
        self, query: str, expected_ids: List[str], **kwargs: Any
    ) -> RetrievalEvalResult:
        """Run evaluation results with query string and expected ids.

        Args:
            query (str): Query string
            expected_ids (List[str]): Expected ids

        Returns:
            RetrievalEvalResult: Evaluation result

        """
        return asyncio.run(
            self.aevaluate(query=query, expected_ids=expected_ids, **kwargs)
        )

    # @abstractmethod
    async def aevaluate(
        self,
        query: str,
        expected_ids: List[str],
        **kwargs: Any,
    ) -> RetrievalEvalResult:
        """Run evaluation with query string, retrieved contexts,
        and generated response string.

        Subclasses can override this method to provide custom evaluation logic and
        take in additional arguments.
        """

        retrieved_ids = await self._aget_retrieved_ids(query)
        metric_dict = {}
        for metric in self.metrics:
            eval_result = metric.compute(query, expected_ids, retrieved_ids)
            metric_dict[metric.metric_name] = eval_result
        return RetrievalEvalResult(
            query=query,
            expected_ids=expected_ids,
            retrieved_ids=retrieved_ids,
            metric_dict=metric_dict,
        )

    async def aevaluate_dataset(
        self, dataset: EmbeddingQAFinetuneDataset, workers: int = 2, **kwargs: Any
    ) -> List[RetrievalEvalResult]:
        """Run evaluation with dataset."""

        semaphore = asyncio.Semaphore(workers)

        async def eval_worker(
            query: str,
            expected_ids: List[str],
        ) -> RetrievalEvalResult:
            async with semaphore:
                return await self.aevaluate(query, expected_ids=expected_ids)

        response_jobs = []
        for query_id, query in dataset.queries.items():
            expected_ids = dataset.relevant_docs[query_id]
            response_jobs.append(eval_worker(query, expected_ids))
        eval_results = await asyncio.gather(*response_jobs)

        return eval_results
