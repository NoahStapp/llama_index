"""Dataset generation from documents"""
from __future__ import annotations

import re
from typing import List, Optional

from llama_index import Document, ServiceContext, SummaryIndex
from llama_index.indices.postprocessor.node import KeywordNodePostprocessor
from llama_index.llms.openai import OpenAI
from llama_index.prompts.base import BasePromptTemplate, PromptTemplate
from llama_index.schema import BaseNode, MetadataMode, NodeWithScore

DEFAULT_QUESTION_GENERATION_PROMPT = """\
Context information is below.
---------------------
{context_str}
---------------------
Given the context information and not prior knowledge.
generate only questions based on the below query.
{query_str}
"""


def _get_default_service_context() -> ServiceContext:
    """Get default service context."""
    llm = OpenAI(temperature=0, model="gpt-3.5-turbo")
    service_context = ServiceContext.from_defaults(llm=llm, chunk_size_limit=3000)
    return service_context


class DatasetGenerator:
    """Generate dataset (question/ question-answer pairs) \
    based on the given documents.

    NOTE: this is a beta feature, subject to change!

    Args:
        nodes (List[Node]): List of nodes. (Optional)
        service_context (ServiceContext): Service Context.
        num_questions_per_chunk: number of question to be \
        generated per chunk. Each document is chunked of size 512 words.
        text_question_template: Question generation template.
        question_gen_query: Question generation query.

    """

    def __init__(
        self,
        nodes: List[BaseNode],
        service_context: Optional[ServiceContext] = None,
        num_questions_per_chunk: int = 10,
        text_question_template: Optional[BasePromptTemplate] = None,
        question_gen_query: Optional[str] = None,
        metadata_mode: MetadataMode = MetadataMode.NONE,
    ) -> None:
        """Init params."""
        if service_context is None:
            service_context = _get_default_service_context()
        self.service_context = service_context
        self.text_question_template = text_question_template or PromptTemplate(
            DEFAULT_QUESTION_GENERATION_PROMPT
        )
        self.question_gen_query = (
            question_gen_query
            or f"You are a Teacher/Professor. Your task is to setup \
                        {num_questions_per_chunk} questions for an upcoming \
                        quiz/examination. The questions should be diverse in nature \
                            across the document. Restrict the questions to the \
                                context information provided."
        )
        self.nodes = nodes
        self._metadata_mode = metadata_mode

    @classmethod
    def from_documents(
        cls,
        documents: List[Document],
        service_context: Optional[ServiceContext] = None,
        num_questions_per_chunk: int = 10,
        text_question_template: Optional[BasePromptTemplate] = None,
        question_gen_query: Optional[str] = None,
        required_keywords: Optional[List[str]] = None,
        exclude_keywords: Optional[List[str]] = None,
    ) -> "DatasetGenerator":
        """Generate dataset from documents."""
        if service_context is None:
            service_context = _get_default_service_context()
        nodes = service_context.node_parser.get_nodes_from_documents(documents)

        # use node postprocessor to filter nodes
        required_keywords = required_keywords or []
        exclude_keywords = exclude_keywords or []
        node_postprocessor = KeywordNodePostprocessor(
            service_context=service_context,
            required_keywords=required_keywords,
            exclude_keywords=exclude_keywords,
        )
        node_with_scores = [NodeWithScore(node=node) for node in nodes]
        node_with_scores = node_postprocessor.postprocess_nodes(node_with_scores)
        nodes = [node_with_score.node for node_with_score in node_with_scores]

        return cls(
            nodes=nodes,
            service_context=service_context,
            num_questions_per_chunk=num_questions_per_chunk,
            text_question_template=text_question_template,
            question_gen_query=question_gen_query,
        )

    def _node_question_generator(
        self, nodes: List[BaseNode], num: Optional[int] = None
    ) -> List[str]:
        """Node question generator."""
        questions: List[str] = []

        for node in nodes:
            if num is not None and len(questions) >= num:
                break
            index = SummaryIndex.from_documents(
                [
                    Document(
                        text=node.get_content(metadata_mode=self._metadata_mode),
                        metadata=node.metadata,
                    )
                ],
                service_context=self.service_context,
            )

            query_engine = index.as_query_engine(
                service_context=self.service_context,
                text_qa_template=self.text_question_template,
                use_async=True,
            )
            response = query_engine.query(
                self.question_gen_query,
            )

            result = str(response).strip().split("\n")
            cleaned_questions = [
                re.sub(r"^\d+[\).\s]", "", question).strip() for question in result
            ]
            questions.extend(cleaned_questions)

        questions = [question for question in questions if question != ""]

        if num is not None:
            questions = questions[:num]
        return questions

    def generate_questions_from_nodes(self, num: Optional[int] = None) -> List[str]:
        """Generates questions for each document."""
        return self._node_question_generator(self.nodes, num)
