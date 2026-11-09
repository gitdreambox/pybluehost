# IXIT — L2CAP group

**IUT:** PyBlueHost on CSR8510 (`usb:0A12:0001#1`)
**Captured:** 2026-06-22

| Item ID | Value | Notes |
|---|---|---|
| TSPX_bd_addr_iut | 00:1A:7D:DA:71:11 | IUT Bluetooth address (CSR8510) |
| TSPX_iut_role_initiator | TRUE | IUT can open L2CAP channels (l2cap-connect REPL cmd) |
| TSPX_iut_role_acceptor | TRUE | IUT accepts incoming L2CAP connections |

> CSR8510 不支持 LE Secure Connections,Classic L2CAP 测试不影响。
> Other `TSPX_*` items (PSM values, MTU, timers) are filled per the specific
> L2CAP test case PTS prompts for. Update this table as PTS requests them.
