import React, { useEffect, useState } from 'react';
import {
  Container,
  Row,
  Col,
  Card,
  Spinner,
  Alert,
  ProgressBar,
  Table
} from 'react-bootstrap';
import Layout from '../components/Layout';

export default function Overview() {
  const [stats, setStats]           = useState(null);
  const [mismatches, setMismatches] = useState([]);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetch('/api/stats').then(res => res.ok ? res.json() : Promise.reject(res.statusText)),
      fetch('/api/mismatches').then(res => res.ok ? res.json() : Promise.reject(res.statusText))
    ])
      .then(([statsData, mismatchData]) => {
        setStats(statsData);
        setMismatches(mismatchData);
      })
      .catch(err => setError(err.toString()))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Layout><Container className="py-4 text-center"><Spinner animation="border" /></Container></Layout>
    );
  }
  if (error) {
    return (
      <Layout><Container className="py-4"><Alert variant="danger">Error: {error}</Alert></Container></Layout>
    );
  }

  const {
    totalEpisodes,
    totalShows,
    totalOverrides,
    totalMissingTitles,
    totalMatches,
    totalMismatches,
    avgConfidence
  } = stats;

  // percentages for the health bar
  const pctMatches   = Math.round((totalMatches / totalEpisodes) * 100);
  const pctOverrides = Math.round((totalOverrides / totalEpisodes) * 100);
  const pctMismatches= Math.round((totalMismatches / totalEpisodes) * 100);
  const pctMissing   = Math.round((totalMissingTitles / totalEpisodes) * 100);

  return (
    <Layout>
      <Container fluid className="py-4">
        <h1 className="mb-4">Library Overview</h1>

        {/* Summary Cards */}
        <Row className="g-4 mb-5">
          <Col xs={6} md={3}>
            <Card bg="dark" text="light" className="text-center">
              <Card.Body>
                <Card.Title>Total Shows</Card.Title>
                <Card.Text style={{ fontSize:'2rem' }}>{totalShows}</Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col xs={6} md={3}>
            <Card bg="dark" text="light" className="text-center">
              <Card.Body>
                <Card.Title>Total Episodes</Card.Title>
                <Card.Text style={{ fontSize:'2rem' }}>{totalEpisodes}</Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col xs={6} md={3}>
            <Card bg="dark" text="light" className="text-center">
              <Card.Body>
                <Card.Title>Fuzzy Matches</Card.Title>
                <Card.Text style={{ fontSize:'2rem' }}>{totalMatches}</Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col xs={6} md={3}>
            <Card bg="dark" text="light" className="text-center">
              <Card.Body>
                <Card.Title>Perfect Matches</Card.Title>
                <Card.Text style={{ fontSize:'2rem' }}>{totalOverrides}</Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col xs={6} md={3}>
            <Card bg="dark" text="light" className="text-center">
              <Card.Body>
                <Card.Title>Mismatches</Card.Title>
                <Card.Text style={{ fontSize:'2rem' }}>{totalMismatches}</Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col xs={6} md={3}>
            <Card bg="dark" text="light" className="text-center">
              <Card.Body>
                <Card.Title>Missing Titles</Card.Title>
                <Card.Text style={{ fontSize:'2rem' }}>{totalMissingTitles}</Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col xs={6} md={3}>
            <Card bg="dark" text="light" className="text-center">
              <Card.Body>
                <Card.Title>Avg. Confidence</Card.Title>
                <Card.Text style={{ fontSize:'2rem' }}>{avgConfidence}</Card.Text>
              </Card.Body>
            </Card>
          </Col>
        </Row>

        {/* Episode Health Bar */}
        <h2 className="mb-3">Episode Health</h2>
        <Card bg="dark" text="light" className="mb-5">
          <Card.Body>
            <ProgressBar>
              <ProgressBar now={pctMatches}    variant="success" key={1}/>
              <ProgressBar now={pctOverrides}   variant="info"    key={2}/>
              <ProgressBar now={pctMismatches}  variant="danger"  key={3}/>
              <ProgressBar now={pctMissing}     variant="warning" key={4}/>
            </ProgressBar>
            
            <div className="health-legend mt-3 d-flex justify-content-center flex-wrap">
              <div className="me-4 d-flex align-items-center">
                <span className="legend-box bg-success me-1"></span>
                <small>Fuzzy Matches ({pctMatches}%)</small>
              </div>
              <div className="me-4 d-flex align-items-center">
                <span className="legend-box bg-info me-1"></span>
                <small>Perfect Matches ({pctOverrides}%)</small>
              </div>
              <div className="me-4 d-flex align-items-center">
                <span className="legend-box bg-danger me-1"></span>
                <small>Problematic Episodes ({pctMismatches}%)</small>
              </div>
              <div className="d-flex align-items-center">
                <span className="legend-box bg-warning me-1"></span>
                <small>Missing Titles ({pctMissing}%)</small>
              </div>
            </div>
          </Card.Body>
        </Card>

        {/* Problematic Episodes by Series */}
        <h2 className="mb-3">Problematic Episodes by Series</h2>
        <Table striped bordered hover responsive variant="dark">
          <thead>
            <tr><th>Series</th><th>Count</th></tr>
          </thead>
          <tbody>
            {mismatches.map(({ seriesTitle, count }) => (
              <tr key={seriesTitle}>
                <td>{seriesTitle}</td>
                <td>{count}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Container>
    </Layout>
  );
}
