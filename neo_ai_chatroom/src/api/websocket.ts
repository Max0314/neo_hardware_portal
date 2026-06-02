import { getWsUrl } from '@/utils/apiBase';

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;
  private listeners: Map<string, Set<(data: any) => void>> = new Map();

  connect(url: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      return;
    }

    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      console.log('WebSocket连接已建立');
      this.reconnectAttempts = 0;
      this.emit('connect', {});
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.emit(data.type, data);
      } catch (error) {
        console.error('解析WebSocket消息失败:', error);
      }
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket错误:', error);
      this.emit('error', { error });
    };

    this.ws.onclose = () => {
      console.log('WebSocket连接已关闭');
      this.emit('disconnect', {});
      this.attemptReconnect(url);
    };
  }

  private attemptReconnect(url: string) {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      setTimeout(() => {
        console.log(`尝试重连 (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
        this.connect(url);
      }, this.reconnectDelay * this.reconnectAttempts);
    }
  }

  send(type: string, data: any) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify({ type, ...data }));
      } catch (error) {
        console.error('发送WebSocket消息失败:', error);
      }
    } else {
      console.warn('WebSocket未连接，当前状态:', this.ws?.readyState);
      // 如果连接关闭，尝试重新连接
      if (this.ws?.readyState === WebSocket.CLOSED) {
        const url = this.ws.url || getWsUrl();
        this.connect(url);
      }
    }
  }
  
  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  on(event: string, callback: (data: any) => void) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(callback);
  }

  off(event: string, callback: (data: any) => void) {
    const callbacks = this.listeners.get(event);
    if (callbacks) {
      callbacks.delete(callback);
    }
  }

  private emit(event: string, data: any) {
    const callbacks = this.listeners.get(event);
    if (callbacks) {
      callbacks.forEach(callback => callback(data));
    }
  }

  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.listeners.clear();
  }
}

export const wsClient = new WebSocketClient();

