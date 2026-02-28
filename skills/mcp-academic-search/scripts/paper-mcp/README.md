# PaperMCP 智能学术论文检索系统

[![smithery badge](https://smithery.ai/badge/@guangxiangdebizi/PaperMCP)](https://smithery.ai/server/@guangxiangdebizi/PaperMCP)

欢迎使用 **PaperMCP 智能学术论文检索系统**！这是一个基于 Model Context Protocol (MCP) 的高级学术论文搜索服务器，专为研究员和教授设计。通过 **OpenAlex API** 和智能算法，为AI助手提供精准的学术文献检索能力，大幅提升科研效率。

## 🌟 Features

### 📚 Comprehensive Paper Search
Search academic papers with flexible filtering options:
* **Keyword Search** - Find papers by title, abstract, or full-text content
* **Country Filter** - Limit results to papers from specific countries (CN, US, GB, etc.)
* **Year Filter** - Search papers from specific publication years
* **Result Limit** - Control the number of results (up to 50 papers)
* **Sort Options** - Sort by citation count, publication date, or relevance
* **Open Access Filter** - Find only freely accessible papers

### 📊 Rich Paper Information
Get comprehensive details for each paper:
* **Basic Info** - Title, authors, publication year, document type
* **Abstract** - Full abstract text with intelligent reconstruction from inverted index
* **Publication Details** - Journal/venue, DOI, URLs
* **Citation Data** - Citation count and related works
* **Institutional Info** - Author affiliations and institutions
* **Subject Classification** - Topics, subfields, fields, and domains
* **Open Access Status** - OA status and APC (Article Processing Charge) information

### 🔍 Advanced Filtering
* **Institution-based Filtering** - Find papers from specific countries' institutions
* **Temporal Filtering** - Search within specific publication years
* **Access-based Filtering** - Filter by open access availability
* **Quality Indicators** - Sort by citation impact or publication date

### 🤖 MCP Integration
Seamless integration with MCP-compatible clients (like Claude) for intelligent academic research

## 🚦 Requirements

Before getting started, please ensure you have:

1. **Node.js and npm**:
   * Requires Node.js version >= 18
   * Download and install from [nodejs.org](https://nodejs.org/)

2. **Email Address**:
   * Provide a valid email address for OpenAlex API access
   * OpenAlex requires an email for rate limiting and contact purposes
   * No API key needed - OpenAlex is free to use!

## 🛠️ Installation & Setup

### Install via Smithery (Recommended)

If you're using Claude Desktop, you can quickly install via [Smithery](https://smithery.ai/server/@guangxiangdebizi/paper-mcp):

```bash
npx -y @smithery/cli install @guangxiangdebizi/paper-mcp --client claude
```

### Manual Installation

1. **Get the code**:
   ```bash
   git clone https://github.com/guangxiangdebizi/PaperMCP.git
   cd PaperMCP
   ```

2. **Install dependencies**:
   ```bash
   npm install
   ```

3. **Configure Email Address**:
   * Create a `.env` file in the project root directory
   * Add the following content:
     ```
     OPENALEX_EMAIL=your_email@example.com
     ```
   * Or set it directly in the `src/config.ts` file

4. **Build the project**:
   ```bash
   npm run build
   ```

## 🚀 Running the Server

There are two ways to start the server:

### Method 1: Using stdio mode (Direct run)

```bash
node build/index.js
```

### Method 2: Using Supergateway (Recommended for development)

```bash
npx supergateway --stdio "node build/index.js" --port 3100
```

## 📝 Configuring MCP Clients

To use this server in Claude or other MCP clients, you need the following configuration:

### Claude Configuration

Add the following to Claude's configuration file:

```json
{
  "mcpServers": {
    "paper-search-server": {
      "url": "http://localhost:3100/sse", // If using Supergateway
      "type": "sse",
      "disabled": false,
      "autoApprove": [
        "paper_search"
      ]
    }
  }
}
```

If using stdio mode directly (without Supergateway), configure as follows:

```json
{
  "mcpServers": {
    "paper-search-server": {
      "command": "C:/path/to/PaperMCP/build/index.js", // Modify to actual path
      "type": "stdio",
      "disabled": false,
      "autoApprove": [
        "paper_search"
      ]
    }
  }
}
```

## 💡 Usage Examples

Here are some example queries using the PaperMCP server:

### 1. Basic Paper Search

You can ask Claude:

**General Search:**
> "Search for papers about machine learning published in 2024"

**Country-specific Search:**
> "Find papers about artificial intelligence from Chinese institutions in 2023"

**Author/Institution Focus:**
> "Search for papers about LLM from US universities in the last 2 years"

### 2. Advanced Filtering

**Citation-based Search:**
> "Find the most-cited papers about deep learning from 2022, limited to 20 results"

**Open Access Papers:**
> "Search for open access papers about natural language processing from 2024"

**Specific Year Range:**
> "Find papers about computer vision published in 2023, sorted by citation count"

### 3. Research-focused Queries

**Literature Review:**
> "Help me find recent papers about transformer architectures for my literature review"

**Trend Analysis:**
> "Search for papers about quantum computing from different countries to analyze research trends"

**Interdisciplinary Research:**
> "Find papers that combine AI and biology, focusing on recent publications"

### 4. Complex Research Queries

**Comparative Analysis:**
> "Compare recent AI research output between China and the US by finding papers from both countries in 2024"

**Field Evolution:**
> "Show me how research in reinforcement learning has evolved by finding papers from 2020-2024"

**Open Science Focus:**
> "Find highly-cited open access papers in machine learning to understand accessible research trends"

This will use the `paper_search` tool to retrieve comprehensive academic paper information.

## 📊 Supported Search Parameters

The PaperMCP server supports the following search parameters:

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `query` | string | Search keywords (required) | "machine learning", "deep learning" |
| `country_code` | string | Filter by country code | "CN" (China), "US" (USA), "GB" (UK) |
| `year` | number | Filter by publication year | 2024, 2023 |
| `num_results` | number | Number of results (max 50) | 10, 20, 50 |
| `sort_by` | string | Sort method | "cited_by_count", "publication_date", "relevance_score" |
| `open_access` | boolean | Filter open access papers | true, false |

## 📈 Data Sources

This server uses the **OpenAlex API**, which provides:

- **260M+ papers** from across all disciplines
- **Real-time updates** with new publications
- **Comprehensive metadata** including citations, authors, institutions
- **Open access information** and APC data
- **Subject classification** at multiple levels
- **Institution and country data** for geographic analysis

## 🔮 Future Plans

Future enhancements may include:

1. **Author Search** - Find papers by specific authors
2. **Institution Search** - Search within specific institutions
3. **Journal/Venue Filtering** - Filter by publication venue
4. **Citation Network Analysis** - Explore citation relationships
5. **Concept-based Search** - Search by research concepts and topics
6. **Export Functionality** - Export results in various formats (BibTeX, etc.)

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## 👨‍💻 Author

- Name: Xingyu_Chen
- Email: guangxiangdebizi@gmail.com
- GitHub: [guangxiangdebizi](https://github.com/guangxiangdebizi)

## 🙏 Acknowledgments

This project uses the [OpenAlex](https://openalex.org/) API, a free and open catalog of scholarly papers, authors, institutions, and more. Special thanks to the OpenAlex team for providing this invaluable resource to the research community.
