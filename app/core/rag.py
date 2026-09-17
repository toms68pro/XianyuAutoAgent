import re
import math
from typing import List, Dict, Any, Optional, Set
from sqlalchemy import select
from loguru import logger
from app.core.database import AsyncSessionLocal
from app.models.entities import FAQ

# 电商与二手高频概念同义词词典 (用于语义泛化与召回增强)
SYNONYMS_MAP: Dict[str, List[str]] = {
    "concept_bargain": ["便宜", "少点", "少点儿", "砍价", "小刀", "大刀", "大砍刀", "能便宜", "能少", "低价", "底价", "优惠", "出不出", "接刀", "自刀", "屠龙刀", "预算"],
    "concept_shipping": ["发货", "快递", "顺丰", "申通", "圆通", "中通", "韵达", "极兔", "包邮", "包邮吗", "运费", "几天到", "今天能发", "今天发", "多久到", "单号", "发货地", "发货时间"],
    "concept_condition": ["成色", "几成新", "划痕", "磕碰", "掉漆", "暗病", "拆修", "拆过", "修过", "进水", "电池", "电池健康", "爱思", "全原", "原装", "纯原", "保修", "在保", "瑕疵"],
    "concept_accessories": ["配件", "包装", "箱说", "发票", "充电器", "充电线", "盒子", "全套", "单机", "裸机", "说明书", "保修卡", "赠品"],
    "concept_authenticity": ["正品", "保真", "支持验货", "验货宝", "专柜", "自提", "面交", "同城", "当面", "秒拍", "秒发", "直发"],
    "concept_compatibility": ["兼容", "支持", "苹果", "安卓", "mac", "windows", "ios", "鸿蒙", "配置", "参数", "type-c", "typec", "蓝牙", "驱动"]
}

# 停用词列表 (高频无实义词过滤)
STOP_WORDS: Set[str] = {
    "的", "了", "在", "吗", "呢", "吧", "呀", "啊", "请问", "你好", "老板", "这个", "那个",
    "一下", "可以", "能不能", "有没有", "怎么", "什么", "支持不", "行不行"
}


class HybridKnowledgeBase:
    """工业级电商混合检索知识库引擎
    
    架构特性：
    1. 细粒度中文分词与 2/3-gram 片段提取
    2. 二手黑话与电商同义词字典网络扩展 (提升模糊长尾召回率)
    3. 完整 BM25 (Best Matching 25) 词频-逆文档频率打分与文档长度惩罚
    4. TF-IDF 稀疏向量余弦相似度 (Cosine Similarity)
    5. 关键词标签强特征加权 + 商品专属优先级加成
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """中文分词、N-gram 片段提取与同义词概念泛化"""
        if not text:
            return []
        
        clean = re.sub(r'[^\w\u4e00-\u9fa5]', ' ', text.lower()).strip()
        raw_words = [w for w in clean.split() if w and w not in STOP_WORDS]
        
        tokens: Set[str] = set(raw_words)
        
        # 提取中文字符串
        chinese_text = re.sub(r'[^\u4e00-\u9fa5]', '', clean)
        # 生成 2-gram 和 3-gram
        n = len(chinese_text)
        for i in range(n - 1):
            bi = chinese_text[i:i+2]
            if bi not in STOP_WORDS:
                tokens.add(bi)
        for i in range(n - 2):
            tri = chinese_text[i:i+3]
            tokens.add(tri)

        # 匹配同义词字典并注入抽象语义概念
        for concept, kw_list in SYNONYMS_MAP.items():
            if any(kw in text for kw in kw_list):
                tokens.add(concept)

        return [t for t in tokens if t]

    def _compute_bm25_scores(self, query_tokens: List[str], docs_tokens: List[List[str]]) -> List[float]:
        """计算 BM25 相关性得分"""
        num_docs = len(docs_tokens)
        if num_docs == 0 or not query_tokens:
            return [0.0] * num_docs

        # 计算文档长度与平均长度
        doc_lens = [len(doc) for doc in docs_tokens]
        avg_doc_len = sum(doc_lens) / num_docs if num_docs > 0 else 1.0

        # 计算每个 query token 在文档集中的出现文档数 (DF)
        df: Dict[str, int] = {}
        for q in query_tokens:
            df[q] = sum(1 for doc in docs_tokens if q in doc)

        # 计算逆文档频率 IDF
        idf: Dict[str, float] = {}
        for q, count in df.items():
            # 经典 BM25 平滑 IDF 公式
            idf[q] = math.log(1.0 + (num_docs - count + 0.5) / (count + 0.5))

        scores = []
        for i, doc in enumerate(docs_tokens):
            score = 0.0
            doc_len = doc_lens[i]
            # 统计词频
            tf_map: Dict[str, int] = {}
            for t in doc:
                tf_map[t] = tf_map.get(t, 0) + 1

            for q in query_tokens:
                if q in tf_map:
                    tf = tf_map[q]
                    numerator = tf * (self.k1 + 1.0)
                    denominator = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / avg_doc_len))
                    score += idf.get(q, 0.0) * (numerator / denominator)
            scores.append(score)

        # 归一化得分至 [0, 1] 区间
        max_score = max(scores) if scores else 0.0
        if max_score > 0:
            return [round(s / max_score, 4) for s in scores]
        return [0.0] * num_docs

    def _compute_cosine_similarity(self, query_tokens: List[str], doc_tokens: List[str]) -> float:
        """计算 Query 与单个文档的向量余弦相似度"""
        if not query_tokens or not doc_tokens:
            return 0.0

        q_set = set(query_tokens)
        d_set = set(doc_tokens)
        all_terms = list(q_set.union(d_set))

        dot_product = 0.0
        q_norm_sq = 0.0
        d_norm_sq = 0.0

        for term in all_terms:
            q_val = 1.0 if term in q_set else 0.0
            d_val = 1.0 if term in d_set else 0.0
            dot_product += q_val * d_val
            q_norm_sq += q_val ** 2
            d_norm_sq += d_val ** 2

        if q_norm_sq == 0 or d_norm_sq == 0:
            return 0.0
        return dot_product / (math.sqrt(q_norm_sq) * math.sqrt(d_norm_sq))

    async def search_relevant_faq(
        self,
        query: str,
        item_id: Optional[str] = None,
        top_k: int = 3,
        min_score: float = 0.35
    ) -> List[Dict[str, Any]]:
        """执行工业级混合检索 (BM25 + Cosine + 标签命中 + 商品匹配)"""
        if not query or not query.strip():
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        async with AsyncSessionLocal() as session:
            # 获取特定商品与全店通用 FAQ
            stmt = select(FAQ).where((FAQ.item_id == item_id) | (FAQ.item_id == None))
            res = await session.execute(stmt)
            faqs = res.scalars().all()

        if not faqs:
            return []

        # 构造文档 Token 集
        docs_tokens = []
        for f in faqs:
            doc_content = f"{f.question} {f.keywords or ''} {f.answer}"
            docs_tokens.append(self._tokenize(doc_content))

        # 1. 计算 BM25 得分
        bm25_scores = self._compute_bm25_scores(query_tokens, docs_tokens)

        # 2. 综合多路打分
        scored = []
        for idx, f in enumerate(faqs):
            doc_token_list = docs_tokens[idx]
            bm25 = bm25_scores[idx]
            cosine = self._compute_cosine_similarity(query_tokens, doc_token_list)

            # 3. 关键词标签精确命中加权
            keyword_bonus = 0.0
            kw_list = [k.strip() for k in (f.keywords or "").split(",") if k.strip()]
            matched_keywords = []
            for kw in kw_list:
                if kw.lower() in query.lower():
                    keyword_bonus += 0.25
                    matched_keywords.append(kw)

            # 4. 商品专属 FAQ 优先加权
            item_bonus = 0.15 if f.item_id and f.item_id == item_id else 0.0

            # 综合最终置信度得分 (权重: BM25 45% + Cosine 35% + 标签 20% + 商品优先加成)
            final_score = min(1.0, 0.45 * bm25 + 0.35 * cosine + keyword_bonus + item_bonus)

            # 找出命中的有效 Token (用于前台审计与调试)
            matched_terms = list(set(query_tokens).intersection(set(doc_token_list)))
            # 过滤内部抽象概念名称
            display_terms = [t for t in matched_terms if not t.startswith("concept_")]

            if final_score >= min_score:
                scored.append({
                    "id": f.id,
                    "item_id": f.item_id,
                    "question": f.question,
                    "answer": f.answer,
                    "keywords": f.keywords or "",
                    "score": round(final_score, 2),
                    "bm25_score": round(bm25, 2),
                    "cosine_score": round(cosine, 2),
                    "matched_keywords": matched_keywords,
                    "matched_terms": display_terms[:5],
                    "is_item_specific": bool(f.item_id)
                })

        # 按置信度降序排序
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    async def format_rag_context(self, query: str, item_id: Optional[str] = None) -> str:
        """格式化检索到的知识库上下文，供 Agent 直接拼装入提示词"""
        matched = await self.search_relevant_faq(query, item_id, top_k=2, min_score=0.4)
        if not matched:
            return ""

        context_lines = ["【知识库精准匹配解答（官方权威答复，请优先采纳）】："]
        for idx, item in enumerate(matched, 1):
            context_lines.append(
                f"{idx}. 问: {item['question']}\n"
                f"   官方标准答复: {item['answer']}\n"
                f"   (置信度: {int(item['score'] * 100)}%)"
            )

        return "\n".join(context_lines)


knowledge_base = HybridKnowledgeBase()
