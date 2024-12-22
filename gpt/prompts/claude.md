# Company Details

- Outboard Parts Warehouse
- Production site: https://odoo.outboardpartswarehouse.com/
- Local development: http://localhost:8069/
- Primary Business: Buying outboard motors, and parting them out on eBay and Shopify

# Development Tools

- IntelliJ IDEA Ultimate 2024.3.1.1
- Odoo Framework Integration plugin
- Odoo 18
- Owl.js 2.0
- Python 3.13.1
- Shopify GraphQL API

# Code Standards

- Pythonic, clean, and elegant code
- Follow Odoo core development patterns and best practices
- Proper use of inheritance and extension mechanisms
- Follow standard Odoo project structure and logging patterns
- PEP 8 compliance
- Descriptive function and variable names that convey purpose clearly instead of comments
- No comments or docstrings in returned code

# Workflow

## Analysis Tools:

- Use `read_multiple_files` over `read_file` for examining multiple files.
- Use `edit_file` when making any changes to existing files:
    - Preserve formatting by matching exact line or pattern changes.
    - Confirm changes by reviewing the output of `read_file`.
- Use `write_file` to create a new file
- Initial file analysis: Use `search_files` with relevant patterns and exclude filters to narrow down results.
- Multi-file analysis: Group related files in `read_multiple_files` calls for efficient processing.
- Limit retrieval to only the necessary snippets or file sections to reduce token usage.
- Use the JetBrains mcpServer plugin to get the context directly from IntelliJ.
- Use the brave-search MCP tool to search the web for new or related information if needed.
- Use the postgres MCP tool to query the database for relevant information if needed.

## Code Review Process:

- Retrieve and examine relevant code, models, and views before analysis or explanation. For example, check model fields,
  XML views, and dependencies.
- Check for dependencies that may be relevant to the issue.
- Validate modifications through manual or automated testing.

# Deployment

- Module location: /Users/cbusillo/PycharmProjects/Odoo-addons/odoo-addons/product_connect
- Deployment environments:
    - opw-prod: Production
    - opw-testing: Testing
    - opw-dev: Development
- GitHub pushes to opw-prod/opw-testing trigger deployments

