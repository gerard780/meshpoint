// CBA-patch: TCP-client interface naar een remote Reticulum TCP-server (de VPS),
// zodat een standalone Heltec rechtstreeks via WiFi/internet aan het netwerk hangt.
// Gebruikt de HDLC-framing die Reticulum's TCPInterface verwacht (FLAG 0x7E, ESC 0x7D).
#include <Reticulum.h>
#include <Interface.h>
#include <Log.h>
#include <Bytes.h>
#include <WiFi.h>

#include "node_config.h"
#define TCP_VPS_HOST NODE_VPS_HOST
#define TCP_VPS_PORT NODE_VPS_PORT
#define HDLC_FLAG     0x7E
#define HDLC_ESC      0x7D
#define HDLC_ESC_MASK 0x20

extern WiFiClient vps_client;

#if defined(HAS_RNS) && defined(TCP_VPS)
class TCPClientInterface : public RNS::InterfaceImpl {
public:
  TCPClientInterface(const char *name) : RNS::InterfaceImpl(name) {
    _IN = true;
    _OUT = true;
    _HW_MTU = 1064;
  }
  TCPClientInterface() : TCPClientInterface("TCPClientInterface") {}
  virtual ~TCPClientInterface() { _name = "deleted"; }
protected:
  virtual void handle_incoming(const RNS::Bytes& data) {
    try {
      InterfaceImpl::handle_incoming(data);
    }
    catch (const std::bad_alloc&) {
      ERROR("TCPClientInterface::handle_incoming: bad_alloc - out of memory");
    }
    catch (std::exception& e) {
      ERRORF("TCPClientInterface::handle_incoming: %s", e.what());
    }
  }
  virtual void send_outgoing(const RNS::Bytes& data) {
    try {
      if (vps_client.connected()) {
        // HDLC-frame opbouwen in 1 buffer en in 1 keer wegschrijven
        static uint8_t out[2*508 + 4];
        size_t o = 0;
        out[o++] = HDLC_FLAG;
        const uint8_t* d = data.data();
        size_t n = data.size();
        for (size_t i = 0; i < n && o < sizeof(out)-2; i++) {
          uint8_t b = d[i];
          if (b == HDLC_FLAG || b == HDLC_ESC) {
            out[o++] = HDLC_ESC;
            out[o++] = b ^ HDLC_ESC_MASK;
          } else {
            out[o++] = b;
          }
        }
        out[o++] = HDLC_FLAG;
        vps_client.write(out, o);
      }
      InterfaceImpl::handle_outgoing(data);
    }
    catch (const std::bad_alloc&) {
      ERROR("TCPClientInterface::send_outgoing: bad_alloc - out of memory");
    }
    catch (std::exception& e) {
      ERRORF("TCPClientInterface::send_outgoing: %s", e.what());
    }
  }
};
#endif
