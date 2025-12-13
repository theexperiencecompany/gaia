"""Docstrings for E2B code execution tool."""

CODE_EXECUTION_TOOL = """
Execute code safely in an isolated E2B sandbox environment.

This tool provides a simple, direct way to run code in a secure WebAssembly-based
sandbox. It executes the provided code and returns stdout, stderr, and exit code.

✅ USE THIS TOOL WHEN:
- User needs to run or test code snippets
- Performing calculations or data processing
- Testing algorithms or code logic
- Generating output, reports, or data visualizations
- Debugging or validating code behavior
- Creating charts, graphs, or plots (with appropriate libraries)
- Running statistical analysis or data science workflows
- Prototyping or experimenting with code

❌ DO NOT USE FOR:
- Simple arithmetic that can be calculated mentally
- Questions that don't require code execution
- File system operations outside the sandbox
- Network requests or external API calls
- Long-running processes or infinite loops
- Code that requires user input or interaction

SUPPORTED LANGUAGES:
- Python (recommended for data analysis, visualization, ML)
- JavaScript (for web-related logic, JSON processing)
- TypeScript (typed JavaScript with enhanced features)
- Ruby (for scripting and text processing)
- PHP (for web development and string manipulation)

PARAMETERS:
- language: Programming language to use (python, javascript, typescript, ruby, php)
- code: The complete code to execute in the sandbox

OUTPUT FORMAT:
Returns a formatted string containing:
- Output: Standard output from the code execution
- Errors: Any error messages or warnings (if present)
- Exit Code: Numeric exit status (0 = success)

EXAMPLES:

Basic Python execution:
✅ execute_code(language="python", code="print('Hello, World!')")

Mathematical calculations:
✅ execute_code(language="python", code="import math\nresult = math.sqrt(144)\nprint(f'Square root of 144 is {result}')")

Data analysis with visualization:
✅ execute_code(language="python", code='''
import matplotlib.pyplot as plt
import numpy as np

# Generate sample data
x = np.linspace(0, 10, 100)
y = np.sin(x)

# Create plot
plt.figure(figsize=(8, 6))
plt.plot(x, y, 'b-', linewidth=2)
plt.title('Sine Wave')
plt.xlabel('x')
plt.ylabel('sin(x)')
plt.grid(True)
plt.show()
''')

JavaScript processing:
✅ execute_code(language="javascript", code="const data = [1, 2, 3, 4, 5]; console.log('Sum:', data.reduce((a, b) => a + b, 0));")

Ruby text processing:
✅ execute_code(language="ruby", code='text = "Hello World"; puts text.upcase.reverse')

BEST PRACTICES:
- Use descriptive variable names and comments for clarity
- Include necessary imports at the beginning of your code
- Handle potential errors gracefully within your code
- For data visualization, use appropriate libraries (matplotlib, seaborn for Python)
- Keep code focused and avoid overly complex operations in a single execution
- Use print statements or console.log to display results clearly

The tool provides real-time streaming progress updates during execution and
comprehensive error reporting for debugging purposes.
"""
