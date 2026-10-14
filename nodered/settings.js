module.exports = {
    flowFile: 'flows.json',
    uiPort: 1880,
    apiMaxLength: '50mb',
    credentialSecret: false,
    functionExternalModules: false,
    functionTimeout: 0,
    logging: { console: { level: 'info', metrics: false, audit: false } },
    editorTheme: { projects: { enabled: false } },
    contextStorage: { default: { module: 'memory' } }
};
