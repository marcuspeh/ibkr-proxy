package broker

// Contract groups the IBKR contract fields shared by every order request.
// Mirrors ibkr-proxy/app/models.py:ContractBase.
type Contract struct {
	Symbol   string `json:"symbol"`
	SecType  string `json:"secType,omitempty"`
	Currency string `json:"currency,omitempty"`
	Exchange string `json:"exchange,omitempty"`
}

// Defaults fills in the proxy-side defaults (STK / USD / SMART).
func (c *Contract) Defaults() {
	if c.SecType == "" {
		c.SecType = "STK"
	}
	if c.Currency == "" {
		c.Currency = "USD"
	}
	if c.Exchange == "" {
		c.Exchange = "SMART"
	}
}

// OrderRequest is the embedded base for limit/market/bracket order
// requests. Mirrors the combined fields of
// ibkr-proxy/app/models.py:{ContractBase, OrderBase}. Kept flat so
// composite-literal initializers at the call site stay readable.
type OrderRequest struct {
	Contract

	Action        string `json:"action"`
	TotalQuantity int    `json:"totalQuantity"`
	OrderRef      string `json:"orderRef,omitempty"`
	OutsideRth    bool   `json:"outsideRth"`
}

type LimitOrderRequest struct {
	OrderRequest
	LmtPrice float64 `json:"lmtPrice"`
	// TIF is the IBKR time-in-force. Defaulted to "GTC" so limit orders
	// persist across sessions. Valid values include DAY, GTC, IOC, FOK, GTD.
	TIF string `json:"tif"`
}

type MarketOrderRequest struct {
	OrderRequest
}

type BracketOrderRequest struct {
	OrderRequest
	LmtPrice float64 `json:"lmtPrice"`
	TPPrice  float64 `json:"tpPrice"`
	SLPrice  float64 `json:"slPrice"`
}

type UpdateOrderRequest struct {
	LmtPrice      *float64 `json:"lmtPrice,omitempty"`
	AuxPrice      *float64 `json:"auxPrice,omitempty"`
	TotalQuantity *int     `json:"totalQuantity,omitempty"`
}

type OrderResponse struct {
	PermId  int    `json:"permId"`
	OrderId int    `json:"orderId"`
	Status  string `json:"status"`
}

type BracketOrderResponse struct {
	ParentPermId  int    `json:"parentPermId"`
	ParentOrderId int    `json:"parentOrderId"`
	Status        string `json:"status"`
}

type PositionResponse struct {
	ConId       int     `json:"conId"`
	Symbol      string  `json:"symbol"`
	Quantity    float64 `json:"quantity"`
	AverageCost float64 `json:"averageCost"`
}

type AccountNAVResponse struct {
	Account  string  `json:"account"`
	NAV      float64 `json:"nav"`
	Currency string  `json:"currency"`
}

type HealthResponse struct {
	Status        string `json:"status"`
	IBKRConnected bool   `json:"ibkr_connected"`
	ClientID      int    `json:"client_id"`
}

type OpenOrderResponse struct {
	PermId        int      `json:"permId"`
	OrderId       int      `json:"orderId"`
	Symbol        string   `json:"symbol"`
	Action        string   `json:"action"`
	TotalQuantity float64  `json:"totalQuantity"`
	LmtPrice      *float64 `json:"lmtPrice,omitempty"`
	AuxPrice      *float64 `json:"auxPrice,omitempty"`
	Status        string   `json:"status"`
	Remaining     float64  `json:"remaining"`
}
