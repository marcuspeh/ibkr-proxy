package broker

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

type Config struct {
	BaseURL string
	Port    int
}

// URL returns the fully-qualified base URL. If Port > 0 it is appended
// to BaseURL as host:port; otherwise BaseURL is assumed complete
// (e.g. "http://example.com" or "http://127.0.0.1:8000").
func (c Config) URL() string {
	if c.Port <= 0 {
		return c.BaseURL
	}
	return fmt.Sprintf("%s:%d", c.BaseURL, c.Port)
}

type BrokerClient struct {
	baseURL string
	client  *http.Client
}

func NewBrokerClient(ctx context.Context, config Config) *BrokerClient {
	return &BrokerClient{
		baseURL: config.URL(),
		client:  &http.Client{},
	}
}

func (c *BrokerClient) doRequest(ctx context.Context, method, path string, body interface{}, response interface{}, idempotencyKey string) error {
	var bodyReader io.Reader
	if body != nil {
		jsonBody, err := json.Marshal(body)
		if err != nil {
			return fmt.Errorf("failed to marshal request body: %w", err)
		}
		bodyReader = bytes.NewReader(jsonBody)
	}

	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, bodyReader)
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	if idempotencyKey != "" {
		req.Header.Set("X-Idempotency-Key", idempotencyKey)
	}

	resp, err := c.client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to execute request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("request failed with status %d: %s", resp.StatusCode, string(respBody))
	}

	if response != nil {
		if err := json.NewDecoder(resp.Body).Decode(response); err != nil {
			return fmt.Errorf("failed to decode response: %w", err)
		}
	}

	return nil
}

func (c *BrokerClient) Health(ctx context.Context) (*HealthResponse, error) {
	var res HealthResponse
	if err := c.doRequest(ctx, "GET", "/health", nil, &res, ""); err != nil {
		return nil, err
	}
	return &res, nil
}

func (c *BrokerClient) PlaceLimitOrder(ctx context.Context, req LimitOrderRequest, idempotencyKey string) (*OrderResponse, error) {
	req.OrderRequest.Contract.Defaults()
	if req.TIF == "" {
		req.TIF = "DAY"
	}
	var res OrderResponse
	if err := c.doRequest(ctx, "POST", "/orders/limit", req, &res, idempotencyKey); err != nil {
		return nil, err
	}
	return &res, nil
}

func (c *BrokerClient) PlaceMarketOrder(ctx context.Context, req MarketOrderRequest, idempotencyKey string) (*OrderResponse, error) {
	req.OrderRequest.Contract.Defaults()
	var res OrderResponse
	if err := c.doRequest(ctx, "POST", "/orders/market", req, &res, idempotencyKey); err != nil {
		return nil, err
	}
	return &res, nil
}

func (c *BrokerClient) PlaceBracketOrder(ctx context.Context, req BracketOrderRequest, idempotencyKey string) (*BracketOrderResponse, error) {
	req.OrderRequest.Contract.Defaults()
	var res BracketOrderResponse
	if err := c.doRequest(ctx, "POST", "/orders/bracket", req, &res, idempotencyKey); err != nil {
		return nil, err
	}
	return &res, nil
}

func (c *BrokerClient) CancelOrder(ctx context.Context, orderID int) error {
	return c.doRequest(ctx, "DELETE", fmt.Sprintf("/orders/%d", orderID), nil, nil, "")
}

func (c *BrokerClient) UpdateOrder(ctx context.Context, orderID int, req UpdateOrderRequest) (*OrderResponse, error) {
	var res OrderResponse
	if err := c.doRequest(ctx, "PUT", fmt.Sprintf("/orders/%d", orderID), req, &res, ""); err != nil {
		return nil, err
	}
	return &res, nil
}

func (c *BrokerClient) GetPositions(ctx context.Context) ([]PositionResponse, error) {
	var res []PositionResponse
	if err := c.doRequest(ctx, "GET", "/positions", nil, &res, ""); err != nil {
		return nil, err
	}
	return res, nil
}

func (c *BrokerClient) GetAccountNAV(ctx context.Context) (*AccountNAVResponse, error) {
	var res AccountNAVResponse
	if err := c.doRequest(ctx, "GET", "/account/nav", nil, &res, ""); err != nil {
		return nil, err
	}
	return &res, nil
}

func (c *BrokerClient) GetOpenOrders(ctx context.Context) ([]OpenOrderResponse, error) {
	var res []OpenOrderResponse
	if err := c.doRequest(ctx, "GET", "/orders/open", nil, &res, ""); err != nil {
		return nil, err
	}
	return res, nil
}
