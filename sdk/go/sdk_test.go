package broker

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestBrokerClient_Methods(t *testing.T) {
	var (
		gotMethod  string
		gotPath    string
		gotIDemKey string
		lastBody   []byte
	)

	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		gotMethod = r.Method
		gotPath = r.URL.Path
		_ = json.NewEncoder(w).Encode(HealthResponse{Status: "ok", IBKRConnected: true, ClientID: 1})
	})
	mux.HandleFunc("/orders/limit", func(w http.ResponseWriter, r *http.Request) {
		gotMethod = r.Method
		gotPath = r.URL.Path
		gotIDemKey = r.Header.Get("X-Idempotency-Key")
		lastBody, _ = io.ReadAll(r.Body)
		_ = json.NewEncoder(w).Encode(OrderResponse{PermId: 11, OrderId: 22, Status: "Submitted"})
	})
	mux.HandleFunc("/orders/market", func(w http.ResponseWriter, r *http.Request) {
		gotMethod = r.Method
		gotPath = r.URL.Path
		lastBody, _ = io.ReadAll(r.Body)
		_ = json.NewEncoder(w).Encode(OrderResponse{PermId: 33, OrderId: 44, Status: "Filled"})
	})
	mux.HandleFunc("/orders/bracket", func(w http.ResponseWriter, r *http.Request) {
		gotMethod = r.Method
		gotPath = r.URL.Path
		lastBody, _ = io.ReadAll(r.Body)
		_ = json.NewEncoder(w).Encode(BracketOrderResponse{ParentPermId: 55, ParentOrderId: 66, Status: "Submitted"})
	})
	mux.HandleFunc("/orders/", func(w http.ResponseWriter, r *http.Request) {
		gotMethod = r.Method
		gotPath = r.URL.Path
		if r.Method == http.MethodPut || r.Method == http.MethodDelete {
			lastBody, _ = io.ReadAll(r.Body)
		}
		if r.Method == http.MethodDelete {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		_ = json.NewEncoder(w).Encode(OrderResponse{PermId: 77, OrderId: 88, Status: "Updated"})
	})
	mux.HandleFunc("/positions", func(w http.ResponseWriter, r *http.Request) {
		gotMethod = r.Method
		gotPath = r.URL.Path
		_ = json.NewEncoder(w).Encode([]PositionResponse{{ConId: 1, Symbol: "AAPL", Quantity: 10, AverageCost: 150}})
	})
	mux.HandleFunc("/account/nav", func(w http.ResponseWriter, r *http.Request) {
		gotMethod = r.Method
		gotPath = r.URL.Path
		_ = json.NewEncoder(w).Encode(AccountNAVResponse{Account: "DU000000", NAV: 12345.67, Currency: "USD"})
	})
	mux.HandleFunc("/orders/open", func(w http.ResponseWriter, r *http.Request) {
		gotMethod = r.Method
		gotPath = r.URL.Path
		_ = json.NewEncoder(w).Encode([]OpenOrderResponse{{PermId: 1, OrderId: 2, Symbol: "AAPL", Action: "BUY", TotalQuantity: 1, Status: "Working", Remaining: 1}})
	})

	srv := httptest.NewServer(mux)
	defer srv.Close()

	c := NewBrokerClient(context.Background(), Config{BaseURL: srv.URL, Port: 0})
	ctx := context.Background()

	// Health
	gotMethod, gotPath = "", ""
	if _, err := c.Health(ctx); err != nil {
		t.Fatalf("Health: %v", err)
	}
	if gotMethod != "GET" || gotPath != "/health" {
		t.Errorf("Health: %s %s", gotMethod, gotPath)
	}

	// PlaceLimitOrder (default TIF + outsideRth)
	gotMethod, gotPath, gotIDemKey = "", "", ""
	if _, err := c.PlaceLimitOrder(ctx, LimitOrderRequest{
		OrderRequest: OrderRequest{Contract: Contract{Symbol: "AAPL"}, Action: "BUY", TotalQuantity: 1, OutsideRth: true},
		LmtPrice:     150.5,
	}, "idem-1"); err != nil {
		t.Fatalf("PlaceLimitOrder: %v", err)
	}
	if gotMethod != "POST" || gotPath != "/orders/limit" || gotIDemKey != "idem-1" {
		t.Errorf("PlaceLimitOrder: %s %s key=%s", gotMethod, gotPath, gotIDemKey)
	}
	if !strings.Contains(string(lastBody), `"secType":"STK"`) || !strings.Contains(string(lastBody), `"currency":"USD"`) {
		t.Errorf("Defaults not applied: %s", lastBody)
	}
	if !strings.Contains(string(lastBody), `"outsideRth":true`) {
		t.Errorf("outsideRth not propagated: %s", lastBody)
	}
	if !strings.Contains(string(lastBody), `"tif":"GTC"`) {
		t.Errorf("default TIF=GTC not applied: %s", lastBody)
	}

	// PlaceLimitOrder (caller-supplied TIF)
	lastBody = nil
	if _, err := c.PlaceLimitOrder(ctx, LimitOrderRequest{
		OrderRequest: OrderRequest{Contract: Contract{Symbol: "AAPL"}, Action: "BUY", TotalQuantity: 1},
		LmtPrice:     150.5,
		TIF:          "DAY",
	}, ""); err != nil {
		t.Fatalf("PlaceLimitOrder DAY: %v", err)
	}
	if !strings.Contains(string(lastBody), `"tif":"DAY"`) {
		t.Errorf("caller TIF=DAY not propagated: %s", lastBody)
	}
	if strings.Contains(string(lastBody), `"tif":"GTC"`) {
		t.Errorf("caller TIF should override default GTC: %s", lastBody)
	}

	// PlaceMarketOrder
	gotMethod, gotPath = "", ""
	if _, err := c.PlaceMarketOrder(ctx, MarketOrderRequest{
		OrderRequest: OrderRequest{Contract: Contract{Symbol: "TSLA"}, Action: "SELL", TotalQuantity: 2},
	}, ""); err != nil {
		t.Fatalf("PlaceMarketOrder: %v", err)
	}
	if gotMethod != "POST" || gotPath != "/orders/market" {
		t.Errorf("PlaceMarketOrder: %s %s", gotMethod, gotPath)
	}

	// PlaceBracketOrder
	gotMethod, gotPath = "", ""
	if _, err := c.PlaceBracketOrder(ctx, BracketOrderRequest{
		OrderRequest: OrderRequest{Contract: Contract{Symbol: "NVDA"}, Action: "BUY", TotalQuantity: 3},
		LmtPrice:     100, TPPrice: 110, SLPrice: 95,
	}, ""); err != nil {
		t.Fatalf("PlaceBracketOrder: %v", err)
	}
	if gotMethod != "POST" || gotPath != "/orders/bracket" {
		t.Errorf("PlaceBracketOrder: %s %s", gotMethod, gotPath)
	}

	// CancelOrder
	gotMethod, gotPath = "", ""
	if err := c.CancelOrder(ctx, 123); err != nil {
		t.Fatalf("CancelOrder: %v", err)
	}
	if gotMethod != "DELETE" || gotPath != "/orders/123" {
		t.Errorf("CancelOrder: %s %s", gotMethod, gotPath)
	}

	// UpdateOrder
	gotMethod, gotPath = "", ""
	price := 999.0
	if _, err := c.UpdateOrder(ctx, 456, UpdateOrderRequest{LmtPrice: &price}); err != nil {
		t.Fatalf("UpdateOrder: %v", err)
	}
	if gotMethod != "PUT" || gotPath != "/orders/456" {
		t.Errorf("UpdateOrder: %s %s", gotMethod, gotPath)
	}

	// GetPositions
	gotMethod, gotPath = "", ""
	if _, err := c.GetPositions(ctx); err != nil {
		t.Fatalf("GetPositions: %v", err)
	}
	if gotMethod != "GET" || gotPath != "/positions" {
		t.Errorf("GetPositions: %s %s", gotMethod, gotPath)
	}

	// GetAccountNAV
	gotMethod, gotPath = "", ""
	if _, err := c.GetAccountNAV(ctx); err != nil {
		t.Fatalf("GetAccountNAV: %v", err)
	}
	if gotMethod != "GET" || gotPath != "/account/nav" {
		t.Errorf("GetAccountNAV: %s %s", gotMethod, gotPath)
	}

	// GetOpenOrders
	gotMethod, gotPath = "", ""
	if _, err := c.GetOpenOrders(ctx); err != nil {
		t.Fatalf("GetOpenOrders: %v", err)
	}
	if gotMethod != "GET" || gotPath != "/orders/open" {
		t.Errorf("GetOpenOrders: %s %s", gotMethod, gotPath)
	}
}
