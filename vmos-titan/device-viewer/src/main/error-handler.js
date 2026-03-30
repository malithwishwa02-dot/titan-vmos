class AppError extends Error {
  constructor(code, userMessage, technicalMessage, severity = 'error') {
    super(technicalMessage || userMessage);
    this.code = code;
    this.userMessage = userMessage;
    this.severity = severity; // 'warn' | 'error' | 'fatal'
  }
}

class ErrorHandler {
  constructor(logger, notifyRenderer) {
    this._log = logger.child('error-handler');
    this._notify = notifyRenderer; // (channel, data) => void

    process.on('uncaughtException', (err) => {
      this._log.error('Uncaught exception:', err.stack || err.message);
      this._sendToRenderer('Unexpected error occurred', err.message);
    });

    process.on('unhandledRejection', (reason) => {
      const msg = reason instanceof Error ? reason.stack || reason.message : String(reason);
      this._log.error('Unhandled rejection:', msg);
      this._sendToRenderer('Unexpected error occurred', msg);
    });
  }

  handle(err) {
    if (err instanceof AppError) {
      this._log[err.severity](`[${err.code}]`, err.message);
      this._sendToRenderer(err.userMessage, err.message);
    } else {
      this._log.error(err.stack || err.message);
      this._sendToRenderer('An error occurred', err.message);
    }
  }

  _sendToRenderer(userMessage, detail) {
    try {
      this._notify('app:error', { message: userMessage, detail });
    } catch {
      // Renderer may not be available
    }
  }
}

module.exports = { AppError, ErrorHandler };
