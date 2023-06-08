"""SMV Retriever.
Largely based on
https://github.com/karpathy/randomfun/blob/master/knn_vs_svm.ipynb"""

from __future__ import annotations

import concurrent.futures
from typing import Any, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel

from langchain.embeddings.base import Embeddings
from langchain.schema import BaseRetriever, Document


def create_index(contexts: List[str], embeddings: Embeddings) -> np.ndarray:
    with concurrent.futures.ThreadPoolExecutor() as executor:
        return np.array(list(executor.map(embeddings.embed_query, contexts)))


def retrieve(query_embeds: np.ndarray,
             index: np.ndarray,
             max_iter: int=10000,
             tol: float=1e-6,
             C: float=0.1) -> Tuple[np.ndarray, np.ndarray]:
    """Function used by langchain.retrievers.svm.SVMRetriever and
    langchain.vectorstores.sklearn.SKLearnSVMVectorStore."""
    from sklearn import svm
    x = np.concatenate([query_embeds[None, ...], index])
    y = np.zeros(x.shape[0])
    y[0] = 1
    clf = svm.LinearSVC(
        class_weight="balanced", verbose=False, max_iter=max_iter, tol=tol, C=C
    )
    clf.fit(x, y)
    similarities = clf.decision_function(x)
    sorted_ix = np.argsort(-similarities)
    # svm.LinearSVC in scikit-learn is non-deterministic.
    # if a text is the same as a query, there is no guarantee
    # the query will be in the first index.
    # this performs a simple swap, this works because anything
    # left of the 0 should be equivalent.
    zero_index = np.where(sorted_ix == 0)[0][0]
    if zero_index != 0:
        sorted_ix[0], sorted_ix[zero_index] = sorted_ix[zero_index], sorted_ix[0]
    denominator = np.max(similarities) - np.min(similarities) + tol
    normalized_similarities = (similarities - np.min(similarities)) / denominator
    return sorted_ix, normalized_similarities


class SVMRetriever(BaseRetriever, BaseModel):
    embeddings: Embeddings
    index: Any
    texts: List[str]
    k: int = 4
    relevancy_threshold: Optional[float] = None

    class Config:

        """Configuration for this pydantic object."""

        arbitrary_types_allowed = True

    @classmethod
    def from_texts(
        cls, texts: List[str], embeddings: Embeddings, **kwargs: Any
    ) -> SVMRetriever:
        index = create_index(texts, embeddings)
        return cls(embeddings=embeddings, index=index, texts=texts, **kwargs)

    def get_relevant_documents(self, query: str) -> List[Document]:
        query_embeds = np.array(self.embeddings.embed_query(query))
        sorted_ix, normalized_similarities = retrieve(query_embeds, self.index)
        top_k_results = []
        for row in sorted_ix[1 : self.k + 1]:
            if (
                self.relevancy_threshold is None
                or normalized_similarities[row] >= self.relevancy_threshold
            ):
                top_k_results.append(Document(page_content=self.texts[row - 1]))
        return top_k_results

    async def aget_relevant_documents(self, query: str) -> List[Document]:
        raise NotImplementedError
