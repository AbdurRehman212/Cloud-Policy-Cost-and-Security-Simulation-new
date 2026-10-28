// Reusable tour definitions. To extend the tour for a new module, append steps here:
// give the page element a stable `data-tour="<name>"` attribute and reference it as `target`.
//
//   route    page that must be open for the step (omit to stay on the current page)
//   target   value of the data-tour attribute to spotlight (omit for a centred message)
//   minRole  hide the step for lower roles (those users do not see the control either)
//   sidebar  open the mobile sidebar first (the target lives inside it)
//   module   label shown in the popover
//
// Rules: only describe controls that exist in the UI. If a target is missing at runtime the
// step is skipped, so a step never points at something that is not there.

export const ROLE_RANK = { viewer: 0, member: 1, admin: 2, owner: 3 };

export const TOUR_STEPS = [
  {
    id: 'welcome',
    route: '/',
    module: 'Welcome',
    title: 'Welcome to the Cloud Simulator',
    text:
      'This is a safe practice cloud. You create virtual servers, watch their health, spot attacks, ' +
      'apply company rules and see what it all costs. Nothing here is real or billed. ' +
      'This short tour shows where everything is. You can skip it at any time.',
  },
  {
    id: 'nav',
    route: '/',
    target: 'nav',
    sidebar: true,
    side: 'right',
    module: 'Getting around',
    title: 'Sidebar menu',
    text:
      'Each item opens one part of the simulator. The highlighted item is the page you are on. ' +
      'The tour will visit these pages in a sensible learning order.',
  },
  {
    id: 'dashboard',
    route: '/',
    target: 'dashboard-header',
    module: 'Dashboard',
    title: 'Dashboard',
    text:
      'A live summary of your resources, security and costs. Use Refresh to reload it. ' +
      'Come back here to see the overall health at a glance.',
  },
  {
    id: 'org-switcher',
    route: '/',
    target: 'org-switcher',
    module: 'Module 2 · Organization',
    title: 'Your organization',
    text:
      'Everything you create belongs to an organization (a team workspace). ' +
      'The coloured tag is your role: owners and admins can manage things, viewers can only look. ' +
      'Open this menu to switch or create organizations.',
  },
  {
    id: 'org-page',
    route: '/organization',
    target: 'org-page',
    module: 'Module 2 · Organization',
    title: 'Organization page',
    text:
      'See your organization details here. On the Members tab you can see the team; admins and owners ' +
      'can invite people by email and choose their role.',
  },
  {
    id: 'data-generator',
    route: '/resources',
    target: 'resources-header',
    module: 'Module 3 · Data Generator',
    title: 'Where the numbers come from',
    text:
      'There is no separate screen for this module. The Data Generator works in the background: ' +
      'for every running server it produces realistic CPU, memory, disk and network readings, ' +
      'based on a dataset baseline. They are simulated values, not from a real cloud.',
  },
  {
    id: 'create-vm',
    route: '/resources',
    target: 'create-vm',
    minRole: 'member',
    module: 'Module 4 · Resource Simulator',
    title: 'Create a virtual machine',
    text:
      'A virtual machine (VM) is a simulated server. Press Create VM, pick a size and name it. ' +
      'It starts as Pending, then becomes Running. The tour will not create one for you.',
  },
  {
    id: 'monitor',
    route: '/resources',
    target: 'resource-tabs',
    module: 'Module 5 · Resource Viewer',
    title: 'Watch your resources',
    text:
      'The Resources tab shows one card per server or database with its status, CPU and memory. ' +
      'Click a card to open its live metrics. Very high CPU means the server is overloaded. ' +
      'The Security Groups tab holds the firewall rules.',
  },
  {
    id: 'simulate-attack',
    route: '/security',
    target: 'simulate-attack',
    minRole: 'admin',
    module: 'Module 6 · Threat Detector',
    title: 'Practise an attack',
    text:
      'Simulate Attack creates a pretend attack (for example a DDoS) so you can see how it is detected. ' +
      'Only admins and owners can use it. Nothing real is attacked.',
  },
  {
    id: 'threats',
    route: '/security',
    target: 'threats-table',
    module: 'Module 6 · Threat Detector',
    title: 'Detected threats',
    text:
      'Threats found for your organization are listed here with type, severity and confidence. ' +
      'Admins can mark one as resolved once it is handled.',
  },
  {
    id: 'compliance',
    route: '/governance',
    target: 'run-compliance',
    module: 'Module 7 · Policy Engine',
    title: 'Check compliance',
    text:
      'Policies are company rules, such as “VM names must start with web-”. ' +
      'Run Compliance Check tests every resource against your active policies and lists the ones that break a rule.',
  },
  {
    id: 'create-policy',
    route: '/governance',
    target: 'create-policy',
    minRole: 'admin',
    module: 'Module 7 · Policy Engine',
    title: 'Write a policy',
    text:
      'Describe a rule in plain English and the system turns it into a check. ' +
      'If the sentence is not understood you will be told so.',
  },
  {
    id: 'cost-by-resource',
    route: '/cost',
    target: 'cost-by-resource',
    module: 'Module 8 · Cost Forecaster',
    title: 'What each resource costs',
    text:
      'Simulated spending per resource, split into compute, storage and network. ' +
      'New rows appear a few moments after a resource starts running.',
  },
  {
    id: 'cost-forecast',
    route: '/cost',
    target: 'cost-forecast',
    module: 'Module 8 · Cost Forecaster',
    title: 'Cost forecast',
    text: 'An estimate of the next 30 days based on your recent spending. It is a projection, not a bill.',
  },
  {
    id: 'budget',
    route: '/cost',
    target: 'create-budget',
    minRole: 'admin',
    module: 'Module 8 · Cost Forecaster',
    title: 'Set a budget',
    text: 'A budget is a spending limit with warning levels. You will see how much of it is used.',
  },
  {
    id: 'reports-pdf',
    route: '/reports',
    target: 'reports-pdf',
    module: 'Module 9 · Report Generator',
    title: 'PDF reports',
    text: 'Download a ready-to-share summary, cost, security or governance report as a PDF.',
  },
  {
    id: 'reports-csv',
    route: '/reports',
    target: 'reports-csv',
    module: 'Module 9 · Report Generator',
    title: 'CSV exports',
    text: 'Download the raw records as CSV to open in a spreadsheet.',
  },
  {
    id: 'help',
    route: '/reports',
    target: 'help',
    module: 'Finished',
    title: 'Need this again?',
    text:
      'Press Help / Take a Tour whenever you want to replay the guide. ' +
      'The Help Assistant button at the bottom right answers common questions about the project.',
  },
];
