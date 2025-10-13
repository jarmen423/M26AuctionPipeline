import axios, { AxiosInstance, AxiosRequestConfig, AxiosError } from 'axios';
import * as cron from 'node-cron';
import * as fs from 'fs/promises';
import * as path from 'path';
import NodeCache from 'node-cache';

// Interfaces for type safety
interface Token {
  access_token: string;
  refresh_token?: string;
  expires_in: number;
  expiry_timestamp: number;
  token_type?: string;
}

interface Config {
  clientId: string;
  clientSecret: string;
  tokenUrl: string;
  refreshUrl?: string; // Fallback if different from tokenUrl
  scope?: string;
  storagePath?: string; // For persisting tokens to file
  proactiveRefreshCron?: string; // e.g., '0 */6 * * *' for every 6 hours
  maxRetries?: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
  logger?: (message: string, level?: 'info' | 'error' | 'warn') => void;
}

// Default logger using console
const defaultLogger = (message: string, level: 'info' | 'error' | 'warn' = 'info') => {
  const timestamp = new Date().toISOString();
  console[level](`[${timestamp}] [TokenRefresher] ${level.toUpperCase()}: ${message}`);
};

// Token storage using NodeCache for in-memory and optional file persistence
class TokenStorage {
  private cache: NodeCache;
  private storagePath: string;

  constructor(storagePath?: string) {
    this.cache = new NodeCache({ stdTTL: 0 }); // No auto-expiry, manage manually
    this.storagePath = storagePath || path.join(__dirname, '..', '..', 'tokens.json');
  }

  async save(token: Token): Promise<void> {
    this.cache.set('current_token', token);
    await fs.writeFile(this.storagePath, JSON.stringify(token, null, 2));
  }

  async load(): Promise<Token | null> {
    try {
      const fileToken = await fs.readFile(this.storagePath, 'utf-8');
      const token: Token = JSON.parse(fileToken);
      this.cache.set('current_token', token);
      return token;
    } catch (error) {
      const cached = this.cache.get<Token>('current_token');
      return cached || null;
    }
  }

  get(): Token | null {
    return this.cache.get<Token>('current_token') || null;
  }

  invalidate(): void {
    this.cache.del('current_token');
  }
}

// Main TokenRefresher class
export class TokenRefresher {
  private config: Config;
  private storage: TokenStorage;
  private httpClient: AxiosInstance;
  private logger: (message: string, level?: 'info' | 'error' | 'warn') => void;
  private isRefreshing: boolean = false;

  constructor(config: Partial<Config> = {}) {
    this.config = {
      clientId: process.env.CLIENT_ID || config.clientId || '',
      clientSecret: process.env.CLIENT_SECRET || config.clientSecret || '',
      tokenUrl: process.env.TOKEN_URL || config.tokenUrl || 'https://api.example.com/oauth/token',
      refreshUrl: process.env.REFRESH_URL || config.refreshUrl,
      scope: process.env.SCOPE || config.scope,
      storagePath: config.storagePath,
      proactiveRefreshCron: config.proactiveRefreshCron || '0 */6 * * *', // Default: every 6 hours
      maxRetries: config.maxRetries || 3,
      baseDelayMs: config.baseDelayMs || 1000,
      maxDelayMs: config.maxDelayMs || 30000,
      logger: config.logger || defaultLogger,
    };

    if (!this.config.clientId || !this.config.clientSecret || !this.config.tokenUrl) {
      throw new Error('Missing required config: CLIENT_ID, CLIENT_SECRET, and TOKEN_URL are mandatory');
    }

    this.storage = new TokenStorage(this.config.storagePath);
    this.logger = this.config.logger!;
    this.httpClient = axios.create({
      baseURL: this.config.tokenUrl,
      timeout: 10000,
    });

    // Load initial token
    this.loadToken().catch(err => this.logger(`Failed to load initial token: ${err.message}`, 'warn'));
  }

  // Detect if token is expired or invalid
  private isTokenExpired(token: Token | null): boolean {
    if (!token) return true;
    return Date.now() >= token.expiry_timestamp;
  }

  // Get current token, refresh if needed
  async getValidToken(): Promise<Token> {
    let token = this.storage.get();
    if (this.isTokenExpired(token)) {
      await this.refreshToken();
      token = this.storage.get();
    }
    if (!token) {
      throw new Error('No valid token available after refresh attempt');
    }
    return token;
  }

  // Refresh token using refresh_token or client credentials
  private async refreshToken(attempt: number = 0): Promise<Token> {
    if (this.isRefreshing) {
      // Avoid concurrent refreshes
      await new Promise(resolve => setTimeout(resolve, 1000));
      return this.getValidToken();
    }

    this.isRefreshing = true;
    try {
      const currentToken = this.storage.get();
      let grantType = 'client_credentials';
      let body: any = {
        grant_type: grantType,
        client_id: this.config.clientId,
        client_secret: this.config.clientSecret,
        scope: this.config.scope,
      };

      // If refresh token available, use refresh_token grant
      if (currentToken?.refresh_token) {
        grantType = 'refresh_token';
        body.refresh_token = currentToken.refresh_token;
        body.scope = this.config.scope;
      }

      const response = await this.httpClient.post(
        this.config.refreshUrl || this.config.tokenUrl,
        new URLSearchParams(body).toString(),
        {
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
          },
        }
      );

      const newToken: Token = {
        ...response.data,
        expiry_timestamp: Date.now() + (response.data.expires_in * 1000) - 300000, // 5 min buffer
      };

      await this.storage.save(newToken);
      this.logger(`Token refreshed successfully (attempt ${attempt + 1})`);
      return newToken;
    } catch (error) {
      const axiosError = error as AxiosError;
      this.logger(`Refresh failed (attempt ${attempt + 1}): ${axiosError.message}`, 'error');

      if (attempt < this.config.maxRetries! - 1) {
        const delay = Math.min(
          this.config.baseDelayMs! * Math.pow(2, attempt),
          this.config.maxDelayMs!
        );
        this.logger(`Retrying in ${delay}ms...`);
        await new Promise(resolve => setTimeout(resolve, delay));
        return this.refreshToken(attempt + 1);
      }

      this.storage.invalidate();
      throw new Error(`Token refresh failed after ${this.config.maxRetries!} attempts: ${axiosError.response?.data || axiosError.message}`);
    } finally {
      this.isRefreshing = false;
    }
  }

  // Load token from storage
  private async loadToken(): Promise<Token | null> {
    const token = await this.storage.load();
    if (token) {
      this.logger('Token loaded from storage');
    }
    return token;
  }

  // Initial token acquisition (if no token exists)
  async acquireInitialToken(): Promise<Token> {
    if (this.storage.get()) {
      return this.getValidToken();
    }
    return this.refreshToken(); // Uses client_credentials for initial
  }

  // Interceptor for Axios to auto-refresh on 401
  getRequestInterceptor(): (config: AxiosRequestConfig) => AxiosRequestConfig {
    return async (config) => {
      const token = await this.getValidToken();
      config.headers = config.headers || {};
      config.headers.Authorization = `${token.token_type || 'Bearer'} ${token.access_token}`;
      return config;
    };
  }

  getResponseInterceptor(): (error: AxiosError) => Promise<AxiosError> {
    return async (error: AxiosError) => {
      if (error.response?.status === 401) {
        this.logger('401 detected, refreshing token...');
        try {
          await this.refreshToken();
          // Retry the original request
          const token = await this.getValidToken();
          error.config!.headers.Authorization = `${token.token_type || 'Bearer'} ${token.access_token}`;
          return this.httpClient.request(error.config!);
        } catch (refreshError) {
          this.logger(`Retry after refresh failed: ${refreshError}`, 'error');
        }
      }
      return Promise.reject(error);
    };
  }

  // Proactive refresh scheduling
  startProactiveRefresh(): void {
    cron.schedule(this.config.proactiveRefreshCron!, async () => {
      const token = this.storage.get();
      if (this.isTokenExpired(token)) {
        this.logger('Proactive refresh triggered');
        await this.refreshToken();
      }
    });
    this.logger(`Proactive refresh scheduled: ${this.config.proactiveRefreshCron!}`);
  }

  stopProactiveRefresh(): void {
    cron.stop();
    this.logger('Proactive refresh stopped');
  }
}

// Usage example (for testing/docs)
// const refresher = new TokenRefresher();
// await refresher.acquireInitialToken();
// const http = axios.create();
// http.interceptors.request.use(refresher.getRequestInterceptor());
// http.interceptors.response.use(undefined, refresher.getResponseInterceptor());
// refresher.startProactiveRefresh();