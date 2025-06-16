import React, { useState, useEffect } from 'react';
import { Container, Row, Col, Navbar, Nav } from 'react-bootstrap';
import './Layout.css';

const Layout = ({ children }) => {
  const [stats, setStats] = useState({
    totalEpisodes: 0,
    totalSeasons: 0,
    totalMismatches: 0,
    totalMissingTitles: 0,
  });

  useEffect(() => {
    fetch('/api/stats')
      .then(res => res.json())
      .then(data => setStats(data))
      .catch(console.error);
  }, []);

  return (
    <>
      <Navbar bg="dark" variant="dark" className="mb-3">
        <Container fluid>
          <Navbar.Brand>Analyzarr</Navbar.Brand>
          <Nav className="ms-auto">
            <Nav.Item className="text-light me-3">
              Episodes: {stats.totalEpisodes}
            </Nav.Item>
            <Nav.Item className="text-light me-3">
              Seasons: {stats.totalSeasons}
            </Nav.Item>
            <Nav.Item className="text-light me-3">
              Mismatches: {stats.totalMismatches}
            </Nav.Item>
            <Nav.Item className="text-light">
              Missing Titles: {stats.totalMissingTitles}
            </Nav.Item>
          </Nav>
        </Container>
      </Navbar>

      <Container fluid>
        <Row>
          <Col xs="auto" className="sidebar p-0">
            <Nav className="flex-column bg-dark vh-100">
              <Nav.Link href="/">Dashboard</Nav.Link>
              <Nav.Link href="/settings">Settings</Nav.Link>
            </Nav>
          </Col>
          <Col className="main-content">
            {children}
          </Col>
        </Row>
      </Container>
    </>
  );
};

export default Layout;
