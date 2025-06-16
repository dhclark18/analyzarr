import React, { useState, useEffect } from 'react';
import { Container, Row, Col, Navbar, Nav } from 'react-bootstrap';
import './Layout.css';

export default function Layout({ children }) {
  const [stats, setStats] = useState({
    totalEpisodes: 0,
    totalSeasons: 0,
    totalMismatches: 0,
    totalMissingTitles: 0,
  });

  useEffect(() => {
    fetch('/api/stats')
      .then(res => res.ok ? res.json() : Promise.reject(res.statusText))
      .then(data => setStats(data))
      .catch(console.error);
  }, []);

  return (
    <>
      <Navbar bg="dark" variant="dark" expand={false} className="mb-3">
        <Navbar.Brand className="ms-3">Analyzarr</Navbar.Brand>
        <Navbar.Collapse className="justify-content-end me-3">
          <Navbar.Text>
            Total Episodes: {stats.totalEpisodes}
          </Navbar.Text>
          <Navbar.Text className="ms-4">
            Seasons: {stats.totalSeasons}
          </Navbar.Text>
          <Navbar.Text className="ms-4">
            Mismatches: {stats.totalMismatches}
          </Navbar.Text>
          <Navbar.Text className="ms-4">
            Missing Titles: {stats.totalMissingTitles}
          </Navbar.Text>
        </Navbar.Collapse>
      </Navbar>

      <Container fluid>
        <Row>
          <Col xs="auto" className="sidebar p-0">
            <Nav className="flex-column bg-dark vh-100">
              <Nav.Link className="text-light">Dashboard</Nav.Link>
              <Nav.Link className="text-light">Settings</Nav.Link>
            </Nav>
          </Col>
          <Col className="main-content">
            {children}
          </Col>
        </Row>
      </Container>
    </>
  );
}
  );
}
