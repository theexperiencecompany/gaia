FLOWCHART_PROMPT = """
    You have the ability to create clear, accurate, and error-free flowcharts using the Mermaid syntax. Only when asked or specified explicitly, you will generate flowcharts based on user inputs while adhering to the following rules:
    Gemerate a flowchart for the description: {description} and direction: {direction}.
    ## Basic Rules

    **Syntax Compliance:** Always use valid Mermaid syntax with the correct structure for nodes, edges, and labels. Ensure there are no syntax errors.

    **Flow Direction:** Default to TD (Top-to-Down) flow unless the user specifies a different direction (LR, BT, or RL).

    ## Node Types
    - Use [] for square-shaped nodes (e.g., A["Node"])
    - Use () for rounded-shaped nodes (e.g., A("Node"))
    - Support multi-line text using HTML break tags (e.g., A["Line 1<br>Line 2"])
    - Ensure the Node Titles are not in double quotes. A["Start"] -->|Procure Materials| B("Rounded Node") . Here A and B are titles.
    - Ensure node descriptions are in double quotes. A["Start"] -->|Procure Materials| B("Rounded Node") . Here Start & Rounded Node are descriptions.
    - Ensure the Node Titles have meaningful but really short 1 word titles. (Not just letters like A and B)
    - **Special Characters:** Replace all special characters in node text and labels with their corresponding HTML entities to prevent syntax errors.

    Examples of Special Characters (included but not limited to). You must follow them:
    A["Text with square brackets: &lsqb;example&rsqb;"]  // For [ and ]
    B("Text with parentheses: &lpar;example&rpar;")      // For ( and )
    D["Text with angle brackets: &lt;example&gt;"]       // For < and >

    ## Connections
    - Use --> for solid connections
    - Use --- for dashed connections
    - Use -.-> for dotted connections
    - Use ==> for thick connections
    - Support edge labels with |Label| (e.g., NodeA -->|Label| NodeB)
    - Alternative label syntax: NodeA -- Label --> NodeB

    ## Best Practices
    - **Decision Clarity:** For decision nodes, ensure all branches (e.g., Yes/No) have clear paths and labels
    - **Detailed:** Ensure that it is very detailed, meaningful and straight to the point. Use subgraphs and different paths for different visualisation.
    - **Styling:** Use appropriate colours, as mentioned below, in order to style the flowchart to make it look good and informative.

    ## Example Output for a Flowchart Request (FOLLOW SIMILIAR SYNTAX IN REGARDS TO DOUBLE QUOTES AND SPACES AND ARROWS AND PIPES "|" EXTREMELY CLOSELY TO AVOID ERRORS)

    flowchart TD
        %% Define Nodes
        A["Start"] -->|Procure Materials| B("Rounded Node")
        B -->|Schedule Production| C{{Decision?}}
        C -->|Yes| D["Do Task 1"]
        C -->|No| E["Do Task 2"]
        D --> F["Process Complete"]
        E --> F

        B -.->|Optional| G("Alternative Path")
        G ==> H{{Another Decision}}
        H -->|Yes| I["Proceed"]
        H -->|No| J["Cancel"]

    ## Complete Node Shapes Reference (Use them properly when needed)

    flowchart TB
        %% Various Shapes
        start["Rectangle"]
        rounded("Rounded Corners")
        stadium[["Stadium Shape"]]
        subroutine[["Subroutine Shape"]]
        database[("Database Shape")]
        circle(("Circle Shape"))
        asymmetric>Asymmetric Shape]
        rhombus{{"Decision Box"}}
        hexagon{{"Hexagon Shape"}}
        parallelogram["Parallelogram"]
        parallelogram_rev["Parallelogram Reversed"]
        trapezoid["Trapezoid"]
        trapezoid_rev["Trapezoid Reversed"]

        %% Different link types
        start --> rounded
        rounded --> stadium
        stadium -.-> subroutine
        subroutine ==> database
        database --- circle
        circle --o asymmetric

        %% Decisions and links with text
        circle --> rhombus
        rhombus -->|Yes| hexagon
        rhombus -->|No| parallelogram
        hexagon --> trapezoid
        parallelogram --> parallelogram_rev

        %% Subgraph Example
        subgraph "ExampleSubgraph"
            direction TB
            sub_start["Sub Start"] --> sub_end["Sub End"]
        end

        start --> ExampleSubgraph

    Use a clear declaration of the flowchart direction (e.g., flowchart LR, flowchart TD, etc.). Use the fill color #00bbff for important nodes.
    IMPORTANT: Do not add any ">" symbols after the "|" (PIPE) symbol.
    Generate only valid Mermaid code per the user description and direction.
"""
