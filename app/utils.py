import re
from typing import List, Dict, Tuple, Any
from urllib.parse import urlparse

# 正则表达式：移除常见的无用参数
PARAM_PATTERN = re.compile(r'[\?&](sid|utm|ref|lang|session|ts)=[^&]*')


def _simplify_url_path(url: str) -> str:
    """
    极度鲁棒的 URL 简化：只保留前两级目录结构，并跳过任何看起来像 ID 或日期的段落。
    """
    try:
        parsed = urlparse(url)
        # 1. 清理查询参数
        path_query = PARAM_PATTERN.sub('', parsed.path + parsed.query)

        # 2. 获取路径分段
        segments = [s for s in path_query.split('/') if s]

        clean_segments = []
        for segment in segments:
            # 规则：如果段落包含数字，或者长度超过 15 个字符 (极可能是 unique slug)，则跳过
            if any(char.isdigit() for char in segment) or len(segment) > 15:
                continue

            # 如果是短的、纯文本的结构性词汇，则保留
            clean_segments.append(segment)

            # 我们只用前两级有意义的目录结构进行聚类（例如 domain/news/article）
            if len(clean_segments) >= 2:
                break

        # 3. 构造聚类 Key: domain/clean_segment1/clean_segment2
        key_segments = clean_segments
        if not key_segments:
            return parsed.netloc

        cluster_key = parsed.netloc + '/' + '/'.join(key_segments)

        return cluster_key.strip('/')
    except Exception:
        return url


def cluster_links(links: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    将链接列表聚类，并为每个集群选出一个代表性的 anchor text 和 URL。
    (此函数依赖于 _simplify_url_path，保持不变)
    """
    if not links:
        return []

    clusters_map = {}

    for link in links:
        url = link['url']
        text = link['text'].strip()

        cluster_key = _simplify_url_path(url)

        if cluster_key not in clusters_map:
            clusters_map[cluster_key] = {
                'id': cluster_key,
                'count': 0,
                'text_counts': {},
                'links': []
            }

        cluster = clusters_map[cluster_key]
        cluster['count'] += 1
        cluster['links'].append(link)

        if text:
            cluster['text_counts'][text] = cluster['text_counts'].get(text, 0) + 1

    final_clusters = []

    for key, cluster in clusters_map.items():
        if cluster['text_counts']:
            rep_text = max(cluster['text_counts'], key=cluster['text_counts'].get)
        else:
            # 如果没有文本，用 Key 作为代表
            rep_text = f"无文本 ({key})"

        final_clusters.append({
            'cluster_id': key,
            'count': cluster['count'],
            'representative_text': rep_text,
            'links': cluster['links']
        })

    return sorted(final_clusters, key=lambda c: c['count'], reverse=True)