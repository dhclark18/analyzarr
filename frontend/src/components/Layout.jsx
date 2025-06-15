import React from 'react';
import { Container, Row, Col, Navbar, Nav } from 'react-bootstrap';
import './Layout.css';

export default function Layout({ children }) {
  return (
    <>
      <Navbar bg="dark" variant="dark" expand={false} className="mb-3">
        <Navbar.Brand className="ms-3">Analyzarr</Navbar.Brand>
      </Navbar>

      <Container fluid>
        <Row>
          <Col xs={1} className="sidebar p-0">
            <Nav className="flex-column bg-dark vh-100">
              <Nav.Link className="text-light">Dashboard</Nav.Link>
              <Nav.Link className="text-light">Settings</Nav.Link>
              {/* add more links here */}
            </Nav>
          </Col>
          <Col xs={11} className="main-content">
            {children}
          </Col>
        </Row>
      </Container>
    </>
  );
}
