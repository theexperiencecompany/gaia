/**
 * Example OpenUI Lang programs for the dev playground
 * (`/dev/openui-samples`). They exercise the adopted `@openuidev/react-ui`
 * component set (Stack/Card/Charts/Table) plus GAIA-only components
 * (GaugeChart, Timeline, FileTree, …) under the GAIA theme.
 */

export interface OpenUIExample {
  id: string;
  name: string;
  code: string;
}

const analyticsDashboard = `root = Stack([header, kpis, charts, bottom], "column", "m")
header = Card([CardHeader("Analytics Dashboard", "Overview of key metrics — last 30 days")], "clear")

kpis = Stack([kpi1, kpi2, kpi3, kpi4], "row", "m", "stretch")
kpi1 = Card([TextContent("Total Revenue", "small"), TextContent("$142,580", "large-heavy"), Tag("+12.4%", null, "sm", "success")], "card")
kpi2 = Card([TextContent("Active Users", "small"), TextContent("38,291", "large-heavy"), Tag("+8.1%", null, "sm", "success")], "card")
kpi3 = Card([TextContent("New Orders", "small"), TextContent("5,847", "large-heavy"), Tag("-2.3%", null, "sm", "danger")], "card")
kpi4 = Card([TextContent("Churn Rate", "small"), TextContent("3.2%", "large-heavy"), Tag("-0.5%", null, "sm", "success")], "card")

charts = Stack([revenueCard, trafficCard], "row", "m", "stretch")
revenueCard = Card([CardHeader("Monthly Revenue", "Jan – Jun 2024"), revenueChart], "card")
revenueChart = BarChart(["Jan", "Feb", "Mar", "Apr", "May", "Jun"], [revenueSeries], "grouped", "Month", "Revenue ($)")
revenueSeries = Series("Revenue", [98200, 105400, 117800, 122300, 134900, 142580])
trafficCard = Card([CardHeader("Website Traffic", "Daily visitors"), trafficChart], "card")
trafficChart = LineChart(["Jan", "Feb", "Mar", "Apr", "May", "Jun"], [organic, paid], "natural", "Month", "Visitors")
organic = Series("Organic", [12400, 13800, 15200, 14700, 16900, 18300])
paid = Series("Paid", [5200, 6100, 5800, 7200, 7900, 8600])

bottom = Stack([ordersCard, pieCard, productsCard], "row", "m", "stretch")
ordersCard = Card([CardHeader("Recent Orders", "Latest transactions"), ordersTable], "card")
ordersTable = Table([orderCol, customerCol, amountCol, statusCol])
orderCol = Col("Order ID", ["#10421", "#10420", "#10419"])
customerCol = Col("Customer", ["Alice Martin", "Bob Chen", "Sara Patel"])
amountCol = Col("Amount", [320.50, 89.99, 540.00], "number")
statusCol = Col("Status", [Tag("Shipped", null, "sm", "success"), Tag("Pending", null, "sm", "warning"), Tag("Shipped", null, "sm", "success")])
pieCard = Card([CardHeader("Revenue by Channel", "Distribution across sources"), pie], "card")
pie = PieChart(["Direct", "Organic", "Paid", "Referral", "Social"], [34, 28, 18, 12, 8], "donut")
productsCard = Card([CardHeader("Top Products", "By revenue this month"), radar], "card")
radar = RadarChart(["Laptop Pro", "Wireless Buds", "Smart Watch", "Tablet X", "USB Hub"], [radarSeries])
radarSeries = Series("Sales Score", [88, 74, 91, 65, 57])`;

const kanbanBoard = `root = Stack([header, board], "column", "m")
header = Card([CardHeader("Kanban Board", "Drag tasks across columns to update their status")], "clear")
board = Stack([todoCol, progressCol, doneCol], "row", "m", "start")

todoCol = Card([todoHeader, todoCards], "sunk", "column", "s")
todoHeader = Stack([TextContent("To Do", "small-heavy"), Tag("3", null, "sm", "neutral")], "row", "s", "center", "between")
todoCards = Stack([todo1, todo2, todo3], "column", "s")
todo1 = Card([Stack([Tag("Feature", null, "sm", "info"), Tag("High", null, "sm", "danger")], "row", "xs"), TextContent("User authentication flow", "small"), TextContent("Due Jan 20", "small")], "card", "column", "xs")
todo2 = Card([Stack([Tag("Bug", null, "sm", "danger")], "row", "xs"), TextContent("Fix broken pagination on mobile", "small"), TextContent("Due Jan 22", "small")], "card", "column", "xs")
todo3 = Card([Stack([Tag("Design", null, "sm", "warning")], "row", "xs"), TextContent("Update dashboard palette", "small"), TextContent("Due Jan 25", "small")], "card", "column", "xs")

progressCol = Card([progressHeader, progressCards], "sunk", "column", "s")
progressHeader = Stack([TextContent("In Progress", "small-heavy"), Tag("2", null, "sm", "info")], "row", "s", "center", "between")
progressCards = Stack([prog1, prog2], "column", "s")
prog1 = Card([Stack([Tag("Feature", null, "sm", "info"), Tag("High", null, "sm", "danger")], "row", "xs"), TextContent("Payment gateway integration", "small"), TextContent("Due Jan 18", "small")], "card", "column", "xs")
prog2 = Card([Stack([Tag("Refactor", null, "sm", "neutral")], "row", "xs"), TextContent("Migrate API to GraphQL", "small"), TextContent("Due Jan 19", "small")], "card", "column", "xs")

doneCol = Card([doneHeader, doneCards], "sunk", "column", "s")
doneHeader = Stack([TextContent("Done", "small-heavy"), Tag("2", null, "sm", "success")], "row", "s", "center", "between")
doneCards = Stack([done1, done2], "column", "s")
done1 = Card([Stack([Tag("Feature", null, "sm", "info")], "row", "xs"), TextContent("Set up CI/CD pipeline", "small"), TextContent("Completed Jan 10", "small")], "card", "column", "xs")
done2 = Card([Stack([Tag("Bug", null, "sm", "danger")], "row", "xs"), TextContent("Fix login redirect loop", "small"), TextContent("Completed Jan 12", "small")], "card", "column", "xs")`;

const gaiaShowcase = `root = Stack([header, top, tree, doc], "column", "m")
header = Card([CardHeader("GAIA Components", "Retained components react-ui has no equivalent for")], "clear")
top = Stack([gaugeCard, timelineCard], "row", "m", "stretch")
gaugeCard = Card([CardHeader("Server Load", "current CPU"), gauge], "card")
gauge = GaugeChart(73, null, 0, 100, "%")
timelineCard = Card([CardHeader("Deploy Activity", "recent events"), timeline], "card")
timeline = Timeline([evt1, evt2, evt3])
evt1 = {"time": "2026-06-26T07:15:00Z", "title": "Deploy succeeded", "description": "main -> production (a3f2c1)", "status": "success", "actor": "github"}
evt2 = {"time": "2026-06-26T06:40:00Z", "title": "Tests passed", "status": "success", "actor": "ci"}
evt3 = {"time": "2026-06-26T06:10:00Z", "title": "Timeout warning", "description": "session cleanup slow", "status": "warning", "actor": "monitor"}
tree = FileTree([f1, f2, f3], "Project Structure")
f1 = {"path": "apps/web/next.config.ts", "size": "1.2 KB"}
f2 = {"path": "apps/api/main.py", "size": "2.8 KB"}
f3 = {"path": "packages/openui/index.ts", "size": "5.1 KB"}
doc = TextDocument("Release Notes", "GAIA now renders generative UI via @openuidev/react-ui, themed to match the product exactly.")`;

const formExample = `root = Card([CardHeader("Feedback", "tell us what you think"), form], "card")
form = Form("feedback", actions, [topicField, msgField])
topicField = FormControl("topic", "Topic", topicSelect)
topicSelect = Select("topic", [opt1, opt2, opt3])
opt1 = SelectItem("Bug report", "bug")
opt2 = SelectItem("Feature request", "feature")
opt3 = SelectItem("Other", "other")
msgField = FormControl("message", "Message", msgInput)
msgInput = TextArea("message", "Type your feedback…")
actions = Buttons([submitBtn])
submitBtn = Button("Submit", null, "primary")`;

export const OPENUI_EXAMPLES: OpenUIExample[] = [
  { id: "analytics", name: "Analytics Dashboard", code: analyticsDashboard },
  { id: "kanban", name: "Kanban Board", code: kanbanBoard },
  { id: "gaia", name: "GAIA Components", code: gaiaShowcase },
  { id: "form", name: "Form", code: formExample },
];
