/**
 * Example OpenUI Lang programs for the dev playground
 * (`/dev/openui-samples`). They exercise the adopted `@openuidev/react-ui`
 * component set (Stack/Card/Charts/Table) plus GAIA-only components
 * (Timeline, FileTree, Map, …) under the GAIA theme.
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
top = Stack([usageCard, timelineCard], "row", "m", "stretch")
usageCard = Card([CardHeader("Resource Usage", "current load"), usage], "card")
usage = RadialChart(["CPU", "Memory", "Disk"], [73, 45, 30])
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

const pricing = `root = Stack([header, plans], "column", "m")
header = Card([CardHeader("Pricing", "Simple, transparent plans")], "clear")
plans = Stack([free, pro, team], "row", "m", "stretch")
free = Card([CardHeader("Free", "for individuals"), TextContent("$0", "large-heavy"), TextContent("Up to 3 projects, community support", "small"), freeBtn], "card", "column", "s")
freeBtn = Button("Get started", null, "secondary")
pro = Card([proTop, TextContent("$20/mo", "large-heavy"), TextContent("Unlimited projects, priority support", "small"), proBtn], "card", "column", "s")
proTop = Stack([TextContent("Pro", "body-heavy"), Tag("Popular", null, "sm", "info")], "row", "s", "center", "between")
proBtn = Button("Upgrade", null, "primary")
team = Card([CardHeader("Team", "for organizations"), TextContent("$80/mo", "large-heavy"), TextContent("SSO, audit logs, dedicated support", "small"), teamBtn], "card", "column", "s")
teamBtn = Button("Contact sales", null, "secondary")`;

const onboarding = `root = Stack([header, steps], "column", "m")
header = Card([CardHeader("Get Started", "Three steps to set up GAIA")], "clear")
steps = Card([Steps([s1, s2, s3])], "card")
s1 = StepsItem("Connect your accounts", "Link Google, Slack, and GitHub so GAIA can act on your behalf")
s2 = StepsItem("Set your preferences", "Tell GAIA how you like to work and when to reach you")
s3 = StepsItem("Start a conversation", "Ask GAIA to plan your day or draft an email")`;

const profile = `root = Card([CardHeader("Account", "Your profile and usage"), body], "card", "column", "m")
body = Stack([user, quota], "column", "m")
user = Avatar("Aryan Kumar", "AK", null, "primary", true)
quota = Stack([p1, p2, p3], "column", "s")
p1 = Progress(72, 100, "primary", "API calls", true)
p2 = Progress(45, 100, "success", "Storage", true)
p3 = Progress(89, 100, "warning", "Rate limit", true)`;

const systemStatus = `root = Stack([header, top, services], "column", "m")
header = Card([CardHeader("System Status", "All systems operational")], "clear")
top = Stack([loadCard, reqCard], "row", "m", "stretch")
loadCard = Card([CardHeader("Resource Load", "by resource"), load], "card")
load = RadialChart(["CPU", "Memory", "Disk"], [62, 48, 30])
reqCard = Card([CardHeader("Requests", "last 6 hours"), reqChart], "card")
reqChart = AreaChart(["1h", "2h", "3h", "4h", "5h", "6h"], [reqSeries], "natural", "Hour", "req/s")
reqSeries = Series("Requests", [120, 160, 140, 200, 240, 210])
services = Card([CardHeader("Services", "current uptime"), svc], "card")
svc = Stack([svc1, svc2, svc3], "column", "s")
svc1 = Stack([TextContent("API", "small"), Tag("Operational", null, "sm", "success")], "row", "s", "center", "between")
svc2 = Stack([TextContent("Database", "small"), Tag("Operational", null, "sm", "success")], "row", "s", "center", "between")
svc3 = Stack([TextContent("Webhooks", "small"), Tag("Degraded", null, "sm", "warning")], "row", "s", "center", "between")`;

const mapDemo = `root = Stack([header, map], "column", "m")
header = Card([CardHeader("NYC Walking Tour", "3 stops with a walking route")], "clear")
map = MapBlock(40.76, -73.975, "Midtown", 13, null, null, stops, route)
stops = [{"lat": 40.758, "lng": -73.9855, "label": "Times Square"}, {"lat": 40.7484, "lng": -73.9857, "label": "Empire State"}, {"lat": 40.7794, "lng": -73.9632, "label": "The Met", "popup": "1000 5th Ave"}]
route = [{"points": [{"lat": 40.758, "lng": -73.9855}, {"lat": 40.7484, "lng": -73.9857}, {"lat": 40.7794, "lng": -73.9632}], "color": "#00bbff"}]`;

const worldMap = `root = Stack([header, map], "column", "m")
header = Card([CardHeader("World", "blank basemap + country borders (GeoJSON)")], "clear")
map = MapBlock(null, null, null, null, true, "https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@v5.1.2/geojson/ne_110m_admin_0_countries.geojson")`;

const complexCharts = `root = Stack([header, row1, row2], "column", "m")
header = Card([CardHeader("Charts", "Complex multi-series chart types")], "clear")
row1 = Stack([stackedCard, areaCard], "row", "m", "stretch")
stackedCard = Card([CardHeader("Revenue by Segment", "stacked bar"), stacked], "card")
stacked = BarChart(["Q1", "Q2", "Q3", "Q4"], [seg1, seg2, seg3], "stacked", "Quarter", "Revenue ($K)")
seg1 = Series("Enterprise", [120, 140, 160, 190])
seg2 = Series("SMB", [80, 90, 85, 110])
seg3 = Series("Consumer", [40, 50, 55, 60])
areaCard = Card([CardHeader("Active Users", "stacked area"), area], "card")
area = AreaChart(["W1", "W2", "W3", "W4", "W5", "W6"], [coh1, coh2], "natural", "Week", "Users")
coh1 = Series("New", [200, 240, 260, 300, 340, 380])
coh2 = Series("Returning", [400, 420, 460, 480, 520, 560])
row2 = Stack([hbarCard, scatterCard], "row", "m", "stretch")
hbarCard = Card([CardHeader("Top Countries", "horizontal bar"), hbar], "card")
hbar = HorizontalBarChart(["USA", "India", "UK", "Germany", "Brazil"], [signups], "grouped", "Signups", "Country")
signups = Series("Signups", [4200, 3800, 2100, 1600, 1400])
scatterCard = Card([CardHeader("Effort vs Impact", "scatter"), scatter], "card")
scatter = ScatterChart([dsNow, dsLater], "Effort", "Impact")
dsNow = ScatterSeries("Now", [n1, n2, n3])
n1 = Point(2, 9)
n2 = Point(4, 7)
n3 = Point(3, 8)
dsLater = ScatterSeries("Later", [l1, l2, l3])
l1 = Point(7, 4)
l2 = Point(8, 6)
l3 = Point(6, 3)`;

const formExample = `root = Card([CardHeader("Feedback", "Tell us what you think"), form], "card")
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
  { id: "pricing", name: "Pricing", code: pricing },
  { id: "onboarding", name: "Onboarding", code: onboarding },
  { id: "profile", name: "Profile", code: profile },
  { id: "status", name: "System Status", code: systemStatus },
  { id: "charts", name: "Complex Charts", code: complexCharts },
  { id: "map", name: "Map (directions)", code: mapDemo },
  { id: "worldmap", name: "Map (data)", code: worldMap },
  { id: "form", name: "Form", code: formExample },
];
