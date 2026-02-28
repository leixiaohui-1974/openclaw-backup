import { OPENALEX_CONFIG } from '../config.js';

export const paperSearch = {
  name: "paper_search",
  description: "智能学术论文检索系统，支持多维度相关性评分、学术质量评估、语义搜索等高级功能，专为研究员和教授设计",
  parameters: {
    type: "object",
    properties: {
      query: {
        type: "string",
        description: "搜索关键词或研究问题，支持自然语言描述，如'transformer架构在自然语言处理中的最新进展'"
      },
      research_focus: {
        type: "string",
        description: "研究重点：cutting_edge(前沿研究，默认)、foundational(基础理论)、survey(综述文献)、empirical(实证研究)、methodological(方法论)",
        enum: ["cutting_edge", "foundational", "survey", "empirical", "methodological"]
      },
      academic_level: {
        type: "string", 
        description: "学术水平：top_tier(顶级期刊/会议)、high_quality(高质量)、mainstream(主流)、all(所有)",
        enum: ["top_tier", "high_quality", "mainstream", "all"]
      },
      time_scope: {
        type: "string",
        description: "时间范围：latest(最新6个月)、recent(最近2年，默认)、established(近5年)、comprehensive(所有时间)",
        enum: ["latest", "recent", "established", "comprehensive"]
      },
      field_specificity: {
        type: "string",
        description: "领域专一性：narrow(精确匹配)、focused(相关领域)、broad(跨学科)，默认focused",
        enum: ["narrow", "focused", "broad"]
      },
      citation_threshold: {
        type: "string",
        description: "引用门槛：highly_cited(高被引)、well_recognized(良好认可)、emerging(新兴)、all(所有)，默认well_recognized",
        enum: ["highly_cited", "well_recognized", "emerging", "all"]
      },
      include_preprints: {
        type: "boolean",
        description: "是否包含预印本论文(arXiv等)，对于获取最前沿研究很重要"
      },
      author_reputation: {
        type: "string",
        description: "作者声誉：renowned(知名学者)、established(成熟研究者)、all(所有)，默认all",
        enum: ["renowned", "established", "all"]
      },
      num_results: {
        type: "number",
        description: "返回论文数量，默认15篇，最多30篇(保证质量)"
      },
      exclude_keywords: {
        type: "string",
        description: "排除关键词，用逗号分隔，如'survey,review,tutorial'可排除综述类文章"
      }
    },
    required: ["query"]
  },
  async run(args: { 
    query: string; 
    research_focus?: string;
    academic_level?: string;
    time_scope?: string;
    field_specificity?: string;
    citation_threshold?: string;
    include_preprints?: boolean;
    author_reputation?: string;
    num_results?: number;
    exclude_keywords?: string;
  }) {
    try {
      console.log(`🔬 启动智能学术检索，查询: ${args.query}`);
      
      const OPENALEX_EMAIL = OPENALEX_CONFIG.EMAIL;
      const OPENALEX_API_URL = OPENALEX_CONFIG.API_URL;
      
      // 设置智能默认参数
      const researchFocus = args.research_focus || 'cutting_edge';
      const academicLevel = args.academic_level || 'high_quality';
      const timeScope = args.time_scope || 'recent';
      const fieldSpecificity = args.field_specificity || 'focused';
      const citationThreshold = args.citation_threshold || 'well_recognized';
      const includePreprints = args.include_preprints !== false; // 默认包含预印本
      const authorReputation = args.author_reputation || 'all';
      const numResults = Math.min(args.num_results || 15, 30);
      
      // 智能搜索策略
      const searchStrategy = await buildIntelligentSearchStrategy({
        query: args.query,
        researchFocus,
        academicLevel,
        timeScope,
        fieldSpecificity,
        citationThreshold,
        includePreprints,
        authorReputation,
        excludeKeywords: args.exclude_keywords
      });
      
      console.log(`📊 使用搜索策略: ${searchStrategy.description}`);
      
      // 执行多阶段检索
      const papers = await executeMultiStageRetrieval(
        searchStrategy, 
        numResults, 
        OPENALEX_EMAIL, 
        OPENALEX_API_URL
      );
      
      if (papers.length === 0) {
        return {
          content: [{ 
            type: "text", 
            text: `🔍 未找到符合条件的高质量论文。\n\n💡 建议：\n1. 尝试使用更宽泛的时间范围\n2. 降低学术水平要求\n3. 扩大领域专一性设置\n4. 检查关键词是否过于具体` 
          }]
        };
      }
      
      // 智能评分和排序
      const rankedPapers = await intelligentRanking(papers, searchStrategy);
      
      // 格式化输出
      const formattedOutput = formatIntelligentResults(rankedPapers, args, searchStrategy);
      
      return {
        content: [{ type: "text", text: formattedOutput }]
      };
      
    } catch (error) {
      console.error('智能论文检索错误:', error);
      return {
        content: [{ 
          type: "text", 
          text: `❌ 检索出现错误: ${error instanceof Error ? error.message : '未知错误'}\n\n💡 请尝试简化搜索条件或检查网络连接` 
        }]
      };
    }
  }
};

// 构建智能搜索策略
async function buildIntelligentSearchStrategy(params: any) {
  const strategy: any = {
    primaryQuery: params.query,
    filters: [],
    sorts: [],
    boosts: [],
    description: ""
  };
  
  // 时间范围智能设置
  const timeRanges = {
    latest: { months: 6, description: "最新6个月" },
    recent: { months: 24, description: "最近2年" },
    established: { months: 60, description: "近5年" },
    comprehensive: { months: null, description: "所有时间" }
  };
  
  const timeRange = timeRanges[params.timeScope as keyof typeof timeRanges];
  if (timeRange.months) {
    const startDate = new Date();
    startDate.setMonth(startDate.getMonth() - timeRange.months);
    const startYear = startDate.getFullYear();
    strategy.filters.push(`publication_year:${startYear}-`);
    strategy.description += `${timeRange.description}，`;
  }
  
  // 学术质量过滤
  switch (params.academicLevel) {
    case 'top_tier':
      // 顶级期刊和会议
      strategy.filters.push('is_in_doaj:false'); // 排除掉一些开放期刊
      strategy.boosts.push({ field: 'cited_by_count', weight: 3.0 });
      strategy.boosts.push({ field: 'apc_usd', weight: 1.5 }); // APC高的通常是好期刊
      strategy.description += "顶级期刊/会议，";
      break;
    case 'high_quality':
      strategy.filters.push('cited_by_count:>5');
      strategy.boosts.push({ field: 'cited_by_count', weight: 2.0 });
      strategy.description += "高质量期刊，";
      break;
    case 'mainstream':
      strategy.filters.push('cited_by_count:>1');
      strategy.description += "主流期刊，";
      break;
  }
  
  // 引用门槛设置
  const citationThresholds = {
    highly_cited: { threshold: 50, description: "高被引" },
    well_recognized: { threshold: 10, description: "良好认可" },
    emerging: { threshold: 2, description: "新兴研究" },
    all: { threshold: 0, description: "所有引用水平" }
  };
  
  const citationConfig = citationThresholds[params.citationThreshold as keyof typeof citationThresholds];
  if (citationConfig.threshold > 0) {
    strategy.filters.push(`cited_by_count:>${citationConfig.threshold}`);
  }
  strategy.description += `${citationConfig.description}，`;
  
  // 研究重点调整
  switch (params.researchFocus) {
    case 'cutting_edge':
      strategy.sorts.push('publication_date:desc');
      strategy.boosts.push({ field: 'publication_year', weight: 2.0 });
      if (params.includePreprints) {
        // 不排除预印本
      } else {
        strategy.filters.push('type:journal-article|proceedings-article');
      }
      strategy.description += "前沿研究重点，";
      break;
    case 'foundational':
      strategy.sorts.push('cited_by_count:desc');
      strategy.boosts.push({ field: 'cited_by_count', weight: 3.0 });
      strategy.filters.push('cited_by_count:>100');
      strategy.description += "基础理论重点，";
      break;
    case 'survey':
      strategy.filters.push('title.search:(review|survey|tutorial|overview)');
      strategy.description += "综述文献重点，";
      break;
    case 'empirical':
      strategy.filters.push('has_fulltext:true');
      strategy.excludeTerms = ['theoretical', 'conceptual', 'review'];
      strategy.description += "实证研究重点，";
      break;
    case 'methodological':
      strategy.includeTerms = ['method', 'approach', 'algorithm', 'framework', 'model'];
      strategy.description += "方法论重点，";
      break;
  }
  
  // 领域专一性
  switch (params.fieldSpecificity) {
    case 'narrow':
      strategy.matchMode = 'exact';
      strategy.description += "精确匹配，";
      break;
    case 'focused':
      strategy.matchMode = 'related';
      strategy.description += "相关领域，";
      break;
    case 'broad':
      strategy.matchMode = 'broad';
      strategy.description += "跨学科，";
      break;
  }
  
  // 排除关键词处理
  if (params.excludeKeywords) {
    const excludeTerms = params.excludeKeywords.split(',').map((term: string) => term.trim());
    strategy.excludeTerms = (strategy.excludeTerms || []).concat(excludeTerms);
    strategy.description += `排除${excludeTerms.join('、')}，`;
  }
  
  // 确保有摘要的高质量论文
  strategy.filters.push('has_abstract:true');
  
  return strategy;
}

// 执行多阶段检索
async function executeMultiStageRetrieval(strategy: any, numResults: number, email: string, apiUrl: string) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 45000); // 增加超时时间
  
  try {
    // 第一阶段：扩展搜索获取候选论文
    const candidateSize = Math.min(numResults * 3, 100); // 获取3倍候选论文
    const candidates = await fetchCandidatePapers(strategy, candidateSize, email, apiUrl, controller);
    
    if (candidates.length === 0) {
      throw new Error('未找到候选论文');
    }
    
    console.log(`📋 获得${candidates.length}个候选论文，开始详细分析...`);
    
    // 第二阶段：获取详细信息并智能过滤
    const detailedPapers = await fetchDetailedPapers(candidates, email, apiUrl, controller);
    
    // 第三阶段：高级过滤
    const filteredPapers = await advancedFiltering(detailedPapers, strategy);
    
    return filteredPapers.slice(0, numResults);
    
  } finally {
    clearTimeout(timeoutId);
  }
}

// 获取候选论文
async function fetchCandidatePapers(strategy: any, candidateSize: number, email: string, apiUrl: string, controller: AbortController) {
  const params: any = {
    search: strategy.primaryQuery,
    mailto: email,
    'per-page': candidateSize,
    sort: strategy.sorts[0] || 'cited_by_count:desc'
  };
  
  // 添加过滤条件
  if (strategy.filters.length > 0) {
    params.filter = strategy.filters.join(',');
  }
  
  const searchUrl = new URL(`${apiUrl}/works`);
  Object.keys(params).forEach(key => {
    searchUrl.searchParams.append(key, params[key]);
  });
  
  const response = await fetch(searchUrl.toString(), {
    signal: controller.signal
  });
  
  if (!response.ok) {
    throw new Error(`OpenAlex API请求失败: ${response.status}`);
  }
  
  const data = await response.json();
  return data.results || [];
}

// 获取详细论文信息
async function fetchDetailedPapers(candidates: any[], email: string, apiUrl: string, controller: AbortController) {
  const detailedPapers = [];
  
  for (let i = 0; i < candidates.length; i++) {
    try {
      const workId = candidates[i].id.split('/').pop();
      const detailUrl = `${apiUrl}/works/${workId}?mailto=${email}`;
      
      const response = await fetch(detailUrl, { signal: controller.signal });
      if (response.ok) {
        const detail = await response.json();
        detailedPapers.push(detail);
      }
      
      // 控制请求频率
      if (i < candidates.length - 1) {
        await new Promise(resolve => setTimeout(resolve, 300));
      }
    } catch (error) {
      console.warn(`获取论文详情失败: ${error}`);
    }
  }
  
  return detailedPapers;
}

// 高级过滤算法
async function advancedFiltering(papers: any[], strategy: any) {
  return papers.filter(paper => {
    // 排除关键词过滤
    if (strategy.excludeTerms) {
      const title = (paper.display_name || '').toLowerCase();
      const abstract = decodeAbstract(paper.abstract_inverted_index || {}).toLowerCase();
      const text = title + ' ' + abstract;
      
      for (const excludeTerm of strategy.excludeTerms) {
        if (text.includes(excludeTerm.toLowerCase())) {
          return false;
        }
      }
    }
    
    // 包含关键词过滤
    if (strategy.includeTerms) {
      const title = (paper.display_name || '').toLowerCase();
      const abstract = decodeAbstract(paper.abstract_inverted_index || {}).toLowerCase();
      const text = title + ' ' + abstract;
      
      const hasIncludeTerm = strategy.includeTerms.some((term: string) => 
        text.includes(term.toLowerCase())
      );
      if (!hasIncludeTerm) {
        return false;
      }
    }
    
    // 质量过滤：确保有基本的学术质量
    if (!paper.abstract_inverted_index || 
        !paper.authorships || 
        paper.authorships.length === 0) {
      return false;
    }
    
    return true;
  });
}

// 智能排序算法
async function intelligentRanking(papers: any[], strategy: any) {
  return papers.map(paper => {
    let score = 0;
    const weights = {
      relevance: 0.3,
      recency: 0.25,
      citations: 0.2,
      quality: 0.15,
      authority: 0.1
    };
    
    // 相关性评分 (基于关键词匹配度)
    const relevanceScore = calculateRelevanceScore(paper, strategy.primaryQuery);
    score += relevanceScore * weights.relevance;
    
    // 时效性评分
    const recencyScore = calculateRecencyScore(paper);
    score += recencyScore * weights.recency;
    
    // 引用影响力评分
    const citationScore = calculateCitationScore(paper);
    score += citationScore * weights.citations;
    
    // 学术质量评分
    const qualityScore = calculateQualityScore(paper);
    score += qualityScore * weights.quality;
    
    // 作者权威性评分
    const authorityScore = calculateAuthorityScore(paper);
    score += authorityScore * weights.authority;
    
    return { ...paper, intelligentScore: score };
  }).sort((a, b) => b.intelligentScore - a.intelligentScore);
}

// 相关性评分计算
function calculateRelevanceScore(paper: any, query: string): number {
  const title = (paper.display_name || '').toLowerCase();
  const abstract = decodeAbstract(paper.abstract_inverted_index || {}).toLowerCase();
  const queryTerms = query.toLowerCase().split(/\s+/);
  
  let titleMatches = 0;
  let abstractMatches = 0;
  
  queryTerms.forEach(term => {
    if (title.includes(term)) titleMatches++;
    if (abstract.includes(term)) abstractMatches++;
  });
  
  const titleScore = (titleMatches / queryTerms.length) * 0.7; // 标题匹配权重更高
  const abstractScore = (abstractMatches / queryTerms.length) * 0.3;
  
  return Math.min(titleScore + abstractScore, 1.0);
}

// 时效性评分计算
function calculateRecencyScore(paper: any): number {
  const currentYear = new Date().getFullYear();
  const paperYear = paper.publication_year || 2000;
  const yearDiff = currentYear - paperYear;
  
  if (yearDiff <= 1) return 1.0;
  if (yearDiff <= 2) return 0.8;
  if (yearDiff <= 3) return 0.6;
  if (yearDiff <= 5) return 0.4;
  return 0.2;
}

// 引用影响力评分计算
function calculateCitationScore(paper: any): number {
  const citations = paper.cited_by_count || 0;
  const yearsSincePublication = new Date().getFullYear() - (paper.publication_year || new Date().getFullYear());
  const avgCitationsPerYear = yearsSincePublication > 0 ? citations / yearsSincePublication : citations;
  
  // 归一化到0-1范围
  if (avgCitationsPerYear >= 20) return 1.0;
  if (avgCitationsPerYear >= 10) return 0.8;
  if (avgCitationsPerYear >= 5) return 0.6;
  if (avgCitationsPerYear >= 2) return 0.4;
  if (avgCitationsPerYear >= 1) return 0.2;
  return 0.1;
}

// 学术质量评分计算
function calculateQualityScore(paper: any): number {
  let score = 0.5; // 基础分
  
  // 期刊质量指标
  const venue = paper.host_venue || {};
  if (venue.is_oa === false) score += 0.2; // 非开放获取通常质量更高
  if (venue.apc_usd && venue.apc_usd > 1000) score += 0.1; // 高APC可能表示高质量
  
  // 摘要质量
  const abstractLength = decodeAbstract(paper.abstract_inverted_index || {}).length;
  if (abstractLength > 100) score += 0.1;
  if (abstractLength > 200) score += 0.1;
  
  return Math.min(score, 1.0);
}

// 作者权威性评分计算
function calculateAuthorityScore(paper: any): number {
  if (!paper.authorships || paper.authorships.length === 0) return 0.2;
  
  let score = 0.2; // 基础分
  
  // 作者数量适中性
  const authorCount = paper.authorships.length;
  if (authorCount >= 2 && authorCount <= 8) score += 0.3;
  
  // 机构多样性
  const institutions = new Set();
  paper.authorships.forEach((authorship: any) => {
    (authorship.institutions || []).forEach((inst: any) => {
      if (inst.display_name) institutions.add(inst.display_name);
    });
  });
  
  if (institutions.size > 1) score += 0.2; // 多机构合作
  if (institutions.size > 3) score += 0.3; // 广泛合作
  
  return Math.min(score, 1.0);
}

// 解码倒排索引摘要
function decodeAbstract(invertedIndex: Record<string, number[]> | null): string {
  if (!invertedIndex) return "【无摘要】";
  
  const pairs: Array<[number, string]> = [];
  for (const [word, positions] of Object.entries(invertedIndex)) {
    for (const position of positions) {
      pairs.push([position, word]);
    }
  }
  
  pairs.sort((a, b) => a[0] - b[0]);
  return pairs.map(pair => pair[1]).join(' ');
}

// 清理HTML标签
function cleanHtml(text: string | null): string {
  if (!text) return '';
  return text.replace(/<[^>]+>/g, '').replace(/&[^;]+;/g, '');
}

// 格式化智能检索结果
function formatIntelligentResults(papers: any[], searchArgs: any, strategy: any): string {
  const searchInfo = `# 🧠 智能学术论文检索结果\n\n` +
    `**🔍 查询**: ${searchArgs.query}\n` +
    `**📊 检索策略**: ${strategy.description}\n` +
    `**🎯 找到高质量论文**: ${papers.length}篇\n` +
    `**⭐ 排序方式**: 智能综合评分 (相关性×时效性×影响力×质量×权威性)\n\n` +
    `${'═'.repeat(100)}\n\n`;
  
  const formattedPapers = papers.map((paper, index) => {
    const title = cleanHtml(paper.display_name || '无标题');
    const year = paper.publication_year || 'N/A';
    const type = paper.type || 'N/A';
    const abstract = decodeAbstract(paper.abstract_inverted_index);
    const score = (paper.intelligentScore * 100).toFixed(1);
    
    // 来源和质量指标
    const venue = paper.host_venue || {};
    const primaryLocation = paper.primary_location || {};
    const source = venue.display_name || primaryLocation.source?.display_name || 'N/A';
    
    // 影响力指标
    const citedByCount = paper.cited_by_count || 0;
    const yearsSince = new Date().getFullYear() - year;
    const avgCitationsPerYear = yearsSince > 0 ? (citedByCount / yearsSince).toFixed(1) : citedByCount;
    
    // 作者和机构
    const authors = (paper.authorships || [])
      .slice(0, 5) // 最多显示5个作者
      .map((authorship: any) => authorship.author?.display_name || 'Unknown');
    
    const institutions = [...new Set(
      (paper.authorships || []).flatMap((authorship: any) => 
        (authorship.institutions || []).map((inst: any) => inst.display_name).filter(Boolean)
      )
    )].slice(0, 3); // 最多显示3个机构
    
    // 学科分类
    const concepts = paper.concepts || [];
    const mainTopics = concepts
      .filter((c: any) => c.level <= 2 && c.score > 0.3)
      .sort((a: any, b: any) => b.score - a.score)
      .slice(0, 3)
      .map((c: any) => c.display_name);
    
    // DOI和链接
    const doi = paper.doi;
    const url = primaryLocation.landing_page_url || paper.id;
    
    // 开放获取和质量指标
    const openAccess = paper.open_access || {};
    const oaStatus = openAccess.oa_status || 'unknown';
    const apc = venue.apc_usd ? `$${venue.apc_usd}` : 'N/A';
    
    // 质量徽章
    let qualityBadges = '';
    if (citedByCount > 100) qualityBadges += '🏆高被引 ';
    if (year >= new Date().getFullYear() - 1) qualityBadges += '🆕最新 ';
    if (oaStatus === 'gold' || oaStatus === 'hybrid') qualityBadges += '🔓开放获取 ';
    if (institutions.length > 2) qualityBadges += '🤝多机构合作 ';
    
    return `## 🎯 ${index + 1}. ${title}\n\n` +
           `**📊 智能评分**: ${score}/100 ${qualityBadges}\n` +
           `**📅 年份**: ${year}  **🔖 类型**: ${type}  **📈 影响力**: ${citedByCount}次引用 (年均${avgCitationsPerYear})\n\n` +
           `**📝 摘要**:\n${abstract}\n\n` +
           `**📖 发表于**: ${source}\n` +
           `**👥 主要作者**: ${authors.join(', ')}${authors.length === 5 ? ' 等' : ''}\n` +
           `**🏛️ 主要机构**: ${institutions.join(', ')}${institutions.length === 3 ? ' 等' : ''}\n` +
           `**🏷️ 主要领域**: ${mainTopics.join(', ') || 'N/A'}\n` +
           `**🔓 开放获取**: ${oaStatus}  **💰 APC**: ${apc}\n` +
           `**🔗 DOI**: ${doi ? `https://doi.org/${doi}` : 'N/A'}\n` +
           `**🌐 链接**: ${url}\n\n` +
           `${'─'.repeat(100)}\n\n`;
  }).join('');
  
  const recommendations = `\n## 💡 检索建议\n\n` +
    `**🎯 优化建议**: 当前检索策略已针对"${searchArgs.research_focus || 'cutting_edge'}"研究重点优化\n` +
    `**📈 质量保证**: 所有结果已通过多维度质量评估，包括相关性、时效性和影响力\n` +
    `**🔄 进一步筛选**: 如需更精确结果，可调整'field_specificity'或'academic_level'参数\n` +
    `**📚 扩展搜索**: 如结果不足，可尝试'comprehensive'时间范围或'broad'领域设置\n\n`;
  
  return searchInfo + formattedPapers + recommendations;
} 