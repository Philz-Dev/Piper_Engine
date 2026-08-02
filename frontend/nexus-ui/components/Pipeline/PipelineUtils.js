import { Box, Database, MessageSquare, Mail, Globe } from 'lucide-react';

export const AVAILABLE_FUNCTIONS = ['upper', 'lower', 'trim', 'length'];

export const fetchEngineSchema = async (serviceName) => {
  return new Promise((resolve) => {
    setTimeout(() => {
      const schemas = {
        "Hubspot.create_contact": {
          firstname: { type: "text", default: "", label: "First Name" },
          lastname: { type: "text", default: "hold", label: "Last Name" },
          email: { type: "email", default: "", label: "Email Address" },
          lifecyclestage: { type: "select", default: "lead", options: ["lead", "subscriber", "customer"], label: "Lifecycle Stage" }
        },
        "Hubspot.search": {
          query: { type: "text", default: "", label: "Search Query" }
        },
        "Hubspot.update_contact": {
          id: { type: "text", default: "", label: "Contact ID" },
          email: { type: "email", default: "", label: "Email Address" }
        },
        "Telegram.alert": {
          authorization: { type: "password", default: "", label: "Bot Token" },
          chat_id: { type: "text", default: "", label: "Chat ID" },
          text: { type: "textarea", default: "Hello from Pipeline!", label: "Message Content" }
        },
        "Slack.message": {
           channel: { type: "text", default: "#general", label: "Channel" },
           message: { type: "textarea", default: "", label: "Message" }
        },
        "Gmail.send": {
          to: { type: "email", default: "", label: "Recipient" },
          subject: { type: "text", default: "", label: "Subject" }
        }
      };
      resolve(schemas[serviceName] || {});
    }, 300);
  });
};

export const INITIAL_DATA = {
  version: "1.0",
  trigger: [{ id: "Typeform_webhook", service: "webhook.Typeform.push" }],
  pipeline: [
    { id: "hubspot_crm_search", service: "Hubspot.search" },
    { 
      id: "hubspot_create", 
      service: "Hubspot.create_contact",
      steps: [
        { id: "telegram_bot", service: "Telegram.alert" },
        { id: "nested_test", service: "Slack.message", steps: [{ id: "deep_nest", service: "Gmail.send" }] }
      ]
    },
    { 
      id: "hubspot_update", 
      service: "Hubspot.update_contact",
      steps: [
        { id: "telegram_bot2", service: "Telegram.alert" }
      ]
    }
  ]
};

export const SAMPLE_PAYLOAD = {
  Typeform_webhook: {
    form_response: {
      definition: { title: "Contact Form" },
      answers: [
        { field: "email", value: "test@example.com" },
        { field: "name", value: "John Doe" }
      ]
    }
  }
};

export const getDisplayService = (service) => {
  if (!service) return 'Unknown';
  const knownApps = ['Hubspot', 'Slack', 'Gmail', 'Telegram', 'Discord', 'webhook'];
  if (knownApps.some(app => service.startsWith(app + '.'))) {
    return service;
  }
  const parts = service.split('.');
  return parts[parts.length - 1];
};

export const getServiceColor = (service) => {
  if (!service) return 'border-zinc-500/30 text-zinc-500';
  if (service.includes('Hubspot')) return 'border-orange-500/30 text-orange-400';
  if (service.includes('Slack')) return 'border-purple-500/30 text-purple-400';
  if (service.includes('Gmail')) return 'border-red-500/30 text-red-400';
  if (service.includes('Telegram')) return 'border-blue-300/30 text-blue-300';
  return 'border-blue-500/30 text-blue-400';
};

export const getServiceIcon = (service) => {
  if (!service) return <Box size={16} />;
  if (service.includes('Hubspot')) return <Database size={16} />;
  if (service.includes('Slack')) return <MessageSquare size={16} />;
  if (service.includes('Gmail')) return <Mail size={16} />;
  if (service.includes('Telegram')) return <MessageSquare size={16} />;
  return <Globe size={16} />;
};

export const AVAILABLE_APPS = [
  { 
    name: "Hubspot", 
    icon: "https://cdn.brandfetch.io/hubspot.com/w/400/h/400",
    desc: "CRM integration", 
    actions: [
      { name: "create_contact", service: "Hubspot.create_contact", category: "CRM", desc: "Create a new contact" },
      { name: "search", service: "Hubspot.search", category: "CRM", desc: "Search contacts" },
      { name: "update_contact", service: "Hubspot.update_contact", category: "CRM", desc: "Update contact details" }
    ] 
  },
  { 
    name: "Timer", 
    icon: "https://cdn.brandfetch.io/clock.com/w/400/h/400",
    desc: "Set execution timer", 
    actions: [
      { name: "now", service: "Timer.now", category: "Triggers", desc: "run now once" },
      { name: "interval", service: "Timer.interval", category: "Triggers", desc: "set intervals for execution" },
    ] 
  },
  { 
    name: "Telegram", 
    icon: "https://cdn.brandfetch.io/telegram.org/w/400/h/400",
    desc: "Messaging app", 
    actions: [
      { name: "alert", service: "Telegram.alert", category: "Notifications", desc: "Send notification" }
    ] 
  },
  { 
    name: "Slack", 
    icon: "https://cdn.brandfetch.io/slack.com/w/400/h/400",
    desc: "Communication platform", 
    actions: [
      { name: "message", service: "Slack.message", category: "Messaging", desc: "Post to channel" }
    ] 
  },
  { 
    name: "Gmail", 
    icon: "https://cdn.brandfetch.io/gmail.com/w/400/h/400",
    desc: "Email service", 
    actions: [
      { name: "send", service: "Gmail.send", category: "Email", desc: "Send an email" }
    ] 
  },
  { 
    name: "Discord", 
    icon: "https://cdn.brandfetch.io/discord.com/w/400/h/400",
    desc: "Chat service", 
    actions: [
      { name: "webhook", service: "Discord.webhook", category: "Triggers", desc: "Push webhook data" }
    ] 
  }
];